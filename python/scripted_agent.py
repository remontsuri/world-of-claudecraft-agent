"""Deterministic geometric baseline agent for World of Claudecraft.

This is the guaranteed-working controller used to prove the training
pipeline end-to-end BEFORE any PPO model is trusted. It walks the full
chain: target_nearest -> turn to face -> approach -> attack -> kill,
then re-acquires the next mob.

Design notes (why it is shaped this way):
- applyAction(turn_left/right) in the game ALSO sets forward=true, so a raw
  turn always drifts. We counter that with a `turn + noop` cadence: turn to
  change facing, noop to let the heading settle with minimal drift.
- Decisions are based on MEASURED state (current facing vs target angle, and
  whether distance actually decreased since last tick), NOT on a fixed
  "turn N steps" count. turn_streak is only a safety cap.
- We never add a turn_in_place action that doesn't exist in the game's 61
  actions -- the agent must learn to work with the real action set.

Action indices are read dynamically from the env's action list at runtime;
the constants below are the v0.36.0 fallback only.

Also serves as the expert policy for later imitation/behavior-cloning:
its (obs, action) trajectories become the dataset PPO is pretrained on.
"""

from __future__ import annotations

import numpy as np

# v0.36.0 default action indices (queried dynamically at runtime from env.action_names)
A_NOOP = 0
A_FORWARD = 1
A_BACK = 2
A_TURN_LEFT = 3
A_TURN_RIGHT = 4
A_TARGET_NEAREST = 8
A_ATTACK = 9

# Geometry thresholds (yards / degrees) -- MELEE_RANGE=5 from sim/types.ts
MELEE_RANGE = 5.0
TURN_EPS_DEG = 20.0
FAR_RANGE = 30.0  # beyond this, just close distance; don't spin in place
TURN_STREAK_CAP = 6  # safety only: never turn more than this many ticks straight
# Hunter/ranged engagement band (classes.ts hunter: maxRange=35, minRange=8)
RANGED_MIN = 8.0
RANGED_MAX = 35.0


class ScriptedController:
    """Measurement-driven controller: ACQUIRE -> TURN -> APPROACH -> COMBAT -> DEAD.

    `decide` is called once per env step with the CURRENT measured state.
    The controller remembers the previous (dist, off_deg) so it can tell
    whether the last action actually helped.
    """

    def __init__(self, action_names: list[str] | None = None):
        self.action_names = action_names
        if action_names is not None:
            self.A_TARGET_NEAREST = action_names.index("target_nearest")
            self.A_ATTACK = action_names.index("attack")
            self.A_FORWARD = action_names.index("forward")
            self.A_BACK = action_names.index("back")
            self.A_TURN_LEFT = action_names.index("turn_left")
            self.A_TURN_RIGHT = action_names.index("turn_right")
            self.A_NOOP = action_names.index("noop")
        else:
            self.A_TARGET_NEAREST = A_TARGET_NEAREST
            self.A_ATTACK = A_ATTACK
            self.A_FORWARD = A_FORWARD
            self.A_BACK = A_BACK
            self.A_TURN_LEFT = A_TURN_LEFT
            self.A_TURN_RIGHT = A_TURN_RIGHT
            self.A_NOOP = A_NOOP
        self.reset()

    def reset(self):
        self.state = "ACQUIRE"
        self._last_target_id = None
        self._prev_dist = None
        self._prev_off = None
        self._turn_streak = 0
        self._noop_pending = False
        self._acq_t = 0

    def decide(self, obs: np.ndarray, target: dict | None) -> tuple[int, str]:
        """Return (action_index, state_label).

        `target` is a dict from the bridge:
          {has: bool, dist: float, off_deg: float, hp: float, id: int}
        """
        hp = float(obs[0])
        dead = bool(obs[10])
        in_combat = bool(obs[11])
        auto_attack = bool(obs[12])

        if dead:
            self.reset()
            return self.A_NOOP, "DEAD"

        if target is None or not target.get("has"):
            # Mobs spawn only when the player moves (idle-mob-tick needs motion).
            # Wander forward most of the time; ping target_nearest periodically
            # so we grab a mob as soon as one spawns nearby.
            self._acq_t = (self._acq_t + 1) % 5
            if self._acq_t == 0:
                self.state = "ACQUIRE"
                return self.A_TARGET_NEAREST, "ACQUIRE"
            self.state = "WANDER"
            return self.A_FORWARD, "WANDER"

        dist = float(target["dist"])
        off_deg = float(target["off_deg"])
        tgt_id = target.get("id")

        # re-acquire if the target we were fighting died / changed
        if self._last_target_id is not None and tgt_id != self._last_target_id:
            self.reset()
            self._last_target_id = tgt_id
            return self.A_TARGET_NEAREST, "RET  "

        # measure whether the last action helped
        dist_decreased = self._prev_dist is None or dist < self._prev_dist - 0.01
        off_improved = self._prev_off is None or abs(off_deg) < abs(self._prev_off)

        # in ranged band: stand and shoot
        if RANGED_MIN <= dist <= RANGED_MAX:
            self._last_target_id = tgt_id
            self._turn_streak = 0
            if not auto_attack:
                self.state = "ENGAGE"
                return self.A_ATTACK, "ENGAGE"
            self.state = "COMBAT"
            return self.A_ATTACK, "COMBAT"

        # too close: back off to keep ranged band
        if dist < RANGED_MIN:
            self._turn_streak = 0
            self._prev_dist = dist
            self._prev_off = off_deg
            self.state = "KITE"
            return self.A_BACK, "KITE"

        # --- out of band: navigate by measured state, not a fixed count ---
        # Far mob: just close distance (forward). Turning in place at 80yd is
        # useless -- approach first, correct angle when close.
        if dist > FAR_RANGE:
            # only hard-turn if the target is way off-heading; otherwise just
            # walk forward (residual angle still closes distance)
            if abs(off_deg) > 60.0:
                self._turn_streak = 0
                self._prev_dist = dist
                self._prev_off = off_deg
                self.state = "TURN"
                return (self.A_TURN_LEFT if off_deg > 0 else self.A_TURN_RIGHT), "TURN"
            self._turn_streak = 0
            self._prev_dist = dist
            self._prev_off = off_deg
            self.state = "APPROACH"
            return self.A_FORWARD, "APPROACH"

        if self._noop_pending:
            # second half of the turn+noop cadence: let heading settle, no drift
            self._noop_pending = False
            self._prev_dist = dist
            self._prev_off = off_deg
            self.state = "TURN"
            return self.A_NOOP, "TURN"

        angle_big = abs(off_deg) > TURN_EPS_DEG

        if angle_big:
            # if turning isn't reducing the angle (or we hit the safety cap),
            # fall through to approach so we don't orbit forever
            if (not off_improved and self._turn_streak >= 2) or self._turn_streak >= TURN_STREAK_CAP:
                self._turn_streak = 0
                self._prev_dist = dist
                self._prev_off = off_deg
                self.state = "APPROACH"
                return self.A_FORWARD, "APPROACH"
            # turn (with the game's built-in forward drift), then noop to settle
            self._turn_streak += 1
            self._prev_dist = dist
            self._prev_off = off_deg
            self._noop_pending = True
            self.state = "TURN"
            return (self.A_TURN_LEFT if off_deg > 0 else self.A_TURN_RIGHT), "TURN"

        # angle small -> approach; if not closing distance, re-turn to correct drift
        if not dist_decreased and self._prev_dist is not None:
            self._turn_streak = 0
            self._prev_dist = dist
            self._prev_off = off_deg
            self.state = "TURN"
            return (self.A_TURN_LEFT if off_deg > 0 else self.A_TURN_RIGHT), "TURN"

        self._turn_streak = 0
        self._prev_dist = dist
        self._prev_off = off_deg
        self.state = "APPROACH"
        return self.A_FORWARD, "APPROACH"


if __name__ == "__main__":
    ctrl = ScriptedController()
    fake_obs = np.zeros(567, dtype=np.float32)
    fake_obs[0] = 1.0
    fake_obs[10] = 0.0
    fake_obs[11] = 1.0
    fake_obs[12] = 0.0
    act, st = ctrl.decide(fake_obs, {"has": True, "dist": 3.0, "off_deg": 5, "hp": 50, "id": 7})
    print(f"action={act} state={st}  (expect attack=9 / ENGAGE)")
