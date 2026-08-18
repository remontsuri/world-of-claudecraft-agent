"""
Hierarchical wrapper over WoWClassicEnv (the headless RL env from world-of-claudecraft).

High-level policy (PPO) chooses a SKILL; the skill executes as a sub-sequence of
low-level actions from src/sim/obs.ts ACTIONS (movement/target/attack/interact/...).
This is Step 6 of the adapter plan: "gradually connect PPO fine-tuning on top of
the adapter" — the high-level layer learns goal/skill selection, the low-level
layer (B1 / obs.ts actions) executes.

Honesty notes:
- loot uses `loot_corpse` (58-capability cmd): server teleports player onto the
  corpse and force-unlocks FFA, so no in-world navigation needed.
- accept_quest / turn_in_quest / sell_junk / gather use the capability cmd surface
  (interact=58, sellAllJunk, harvestNode, turnInQuest) — all server-supported.
- farm uses target_nearest (8) + attack (9).
- craft/equip/buy are unsupported in headless: no recipe/buy/equip cmd exists in
  the capability surface; honest noop (Phase D will mask them).
- Reward is computed from env.info deltas (quests_done, copper, kills) — same
  signals the low-level env already tracks, no fabricated values.
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import math
from typing import Optional

from wow_env import WoWClassicEnv, make_env

# High-level skill set — MUST match the 10-skill plan in TRAINING.md (fixed indices):
#   0 farm  1 loot  2 accept_quest  3 turn_in_quest  4 sell_junk
#   5 gather  6 craft  7 heal  8 equip  9 buy
# Order is load-bearing: Phase D high-level PPO trains against these indices.
SKILLS = ["farm", "loot", "accept_quest", "turn_in_quest", "sell_junk",
          "gather", "craft", "heal", "equip", "buy"]
N_SKILLS = len(SKILLS)

# Low-level action indices from src/sim/obs.ts ACTIONS
ACT_FORWARD = 1
ACT_TURN_LEFT = 3
ACT_TURN_RIGHT = 4
ACT_STRAFE_RIGHT = 6
ACT_TARGET_NEAREST = 8
ACT_ATTACK = 9
ACT_INTERACT = 58
ACT_EAT_DRINK = 60
ACT_NOOP = 0  # stop moving + stop attacking not in obs.ts ACTIONS; use noop

# How many low-level steps a skill may run before returning control.
# unsupported-in-headless skills (craft/equip/buy) run 1 step (honest noop).
SKILL_STEPS = {"farm": 10, "loot": 30, "accept_quest": 10, "turn_in_quest": 10,
               "sell_junk": 1, "gather": 20, "craft": 1, "heal": 30, "equip": 1, "buy": 1}


class HierarchicalWoWEnv(gym.Env):
    """High-level env: action = skill id, observation = world-state summary."""

    metadata = {"render_modes": []}

    def __init__(self, player_class: str = "warrior", max_steps: int = 2000,
                 frame_skip: int = 5, seed: int = 0, player_level: int = 1):
        super().__init__()
        self.base = WoWClassicEnv(
            player_class=player_class, max_steps=max_steps * 100, frame_skip=frame_skip
        )
        self.max_high_steps = max_steps
        self.seed_base = seed
        self.player_level = player_level

        self.action_space = spaces.Discrete(N_SKILLS)
        # [level/20, xp_norm, kills/50, quests_done/10, copper/1000, hp_norm, in_combat]
        self.observation_space = spaces.Box(
            low=-2.0, high=2.0, shape=(7,), dtype=np.float32
        )
        self._high_step = 0
        self._last_info = None

    # ---- high-level observation from base env info ----
    def _hl_obs(self, info: dict) -> np.ndarray:
        lvl = info.get("level", 1) / 20.0
        # xp is cumulative; normalize loosely
        xp = min(info.get("xp", 0) / 10000.0, 2.0)
        kills = min(info.get("kills", 0) / 50.0, 2.0)
        qd = min(info.get("quests_done", 0) / 10.0, 2.0)
        copper = min(info.get("copper", 0) / 1000.0, 2.0)
        hp = 1.0  # base env does not expose hp in info reliably; placeholder
        combat = 0.0
        return np.array([lvl, xp, kills, qd, copper, hp, combat], dtype=np.float32)

    # ---- navigation: turn to target, move forward, wall-follow on stuck ----
    def _navigate_to_target(self, max_steps: int = 40):
        """Move toward the currently targeted entity. Returns True if close enough
        to attack (targetDist small). Uses stuck-detection + sidestep (wall-follow)."""
        last_pos = None
        stuck = 0
        for _ in range(max_steps):
            info = self._last_info
            off = info.get("targetOffDeg")
            tdist = info.get("targetDist")
            if tdist is not None and tdist < 8:
                return True  # in attack range
            if off is None:
                # no target bearing; re-acquire
                _, _, _, _, info = self.base.step(ACT_TARGET_NEAREST)
                self._last_info = info
                continue
            # turn toward target
            if abs(off) > 4:
                _, _, _, _, info = self.base.step(ACT_TURN_RIGHT if off > 0 else ACT_TURN_LEFT)
                self._last_info = info   # MUST refresh bearing for next iter
                continue
            # move forward
            _, _, _, _, info = self.base.step(ACT_FORWARD)
            self._last_info = info
            # stuck detection
            pos = info.get("player_pos")
            if last_pos is not None and abs(pos[0] - last_pos[0]) < 0.3 and abs(pos[1] - last_pos[1]) < 0.3:
                stuck += 1
                if stuck >= 3:
                    # wall-follow: sidestep + small turn
                    self.base.step(ACT_STRAFE_RIGHT)
                    self.base.step(ACT_TURN_RIGHT)
                    stuck = 0
            else:
                stuck = 0
            last_pos = pos
        return False

    def _navigate_to_coord(self, tx: float, tz: float, max_steps: int = 60) -> bool:
        """Move toward an arbitrary world coord (tx,tz). Returns True if arrived
        within ~5 units. Turn-to-bearing + forward + wall-follow on stuck."""
        last_pos = None
        stuck = 0
        best_dist = None
        no_progress = 0
        for _ in range(max_steps):
            info = self._last_info
            px, pz = info.get("player_pos", [0, 0])
            dx = tx - px
            dz = tz - pz
            dist = (dx * dx + dz * dz) ** 0.5
            if dist < 5:
                return True
            # give up if we haven't closed distance for many steps (target moving
            # away, e.g. a fleeing mob). Avoiding a long turn/forward grind here is
            # what keeps the node server alive (the "navigation instability" crash).
            if best_dist is None or dist < best_dist - 0.5:
                best_dist = dist
                no_progress = 0
            else:
                no_progress += 1
                if no_progress >= 30:
                    return False
            # Bearing to (tx,tz) in the sim's own convention.
            #
            # MEASURED FACTS (see _diag_nav3.py / _diag_navab.py, and confirmed by
            # src/sim/player_motion.ts:286 "facing f points along (sin f, cos f)...
            # Turning right therefore DECREASES facing"):
            #   1. heading vector is (sin facing, cos facing) -> bearing is
            #      atan2(dx, dz), NOT atan2(dx, -dz). The old form was off by
            #      ~80 deg on average and steered the player away.
            #   2. turn_right DECREASES facing, so a POSITIVE off (we need facing
            #      to increase) requires turn_LEFT. The old code turned the wrong way.
            #   3. facing is QUANTIZED to 45 deg steps (8 headings), so the old
            #      |off| <= 4 gate was unreachable and the loop turned forever
            #      without ever stepping forward. Gate must be >= half a step (22.5).
            # A/B result (seed 42): V0 old = never arrived (dist 22.3 -> 31.6),
            # V3 this = arrived in 27 steps (dist 22.3 -> 5.0).
            want = math.degrees(math.atan2(dx, dz))
            facing = math.degrees(info.get("facing") or 0.0)
            off = ((want - facing + 180.0) % 360.0) - 180.0
            if abs(off) > 22.5:
                _, _, _, _, info = self.base.step(ACT_TURN_LEFT if off > 0 else ACT_TURN_RIGHT)
                self._last_info = info   # MUST refresh facing for next iter
                continue
            _, _, _, _, info = self.base.step(ACT_FORWARD)
            self._last_info = info
            pos = info.get("player_pos")
            if last_pos is not None and abs(pos[0] - last_pos[0]) < 0.3 and abs(pos[1] - last_pos[1]) < 0.3:
                stuck += 1
                if stuck >= 3:
                    self.base.step(ACT_STRAFE_RIGHT)
                    self.base.step(ACT_TURN_RIGHT)
                    stuck = 0
            else:
                stuck = 0
            last_pos = pos
        return False

    def _navigate_along_path(self, waypoints: list, max_steps_per_leg: int = 60) -> bool:
        """Walk a list of {x,z} waypoints (server A* path) to the final point.
        Returns True if the final waypoint is reached within tolerance.
        Robust to long distances with obstacles — steps leg-by-leg instead of
        grinding one straight line into terrain."""
        if not waypoints:
            return False
        for wp in waypoints:
            if not self._navigate_to_coord(wp.get("x"), wp.get("z"), max_steps=max_steps_per_leg):
                return False
        return True

    # ---- skill executors (sub-sequences of low-level actions) ----
    def _run_skill(self, skill_idx: int):
        """Execute one skill as low-level steps. Returns (reward_delta, done)."""
        name = SKILLS[skill_idx]
        info0 = self._last_info
        q0 = info0.get("quests_done", 0)
        c0 = info0.get("copper", 0)
        k0 = info0.get("kills", 0)

        n = SKILL_STEPS.get(name, 5)
        for _ in range(n):
            # defaults for vars only some branches assign (loot returns a dict
            # via loot_corpse, not a 5-tuple)
            obs, r, term, trunc, info = None, 0.0, False, False, self._last_info
            if name == "farm":
                # navigate toward nearest mob, then attack (headless world IS populated;
                # mobs spawn ~46u from start, so we must move toward them)
                self.base.step(ACT_TARGET_NEAREST)
                in_range = self._navigate_to_target(max_steps=30)
                if in_range and self._last_info.get("targetId") is not None:
                    obs, r, term, trunc, info = self.base.step(ACT_ATTACK)
                else:
                    # not reachable this skill-call: stop pushing (avoids server
                    # crash from grinding forward into a wall / void). Control
                    # returns to the GoalManager, which can roam or pick another goal.
                    break
            elif name == "loot":
                # loot via dedicated command (command teleports player onto the
                # corpse and force-unlocks FFA, so no in-world navigation needed)
                corpses = [e for e in (self._last_info.get("nearby") or [])
                           if (e.get("type") == "corpse" or e.get("kind") == "corpse"
                               or e.get("lootable")) and not e.get("looted")]
                if not corpses:
                    obs, r, term, trunc, info = self.base.step(ACT_NOOP)
                else:
                    corpses.sort(key=lambda e: e.get("dist", 1e9))
                    cid = corpses[0].get("id")
                    if cid is not None:
                        info = self.base.loot_corpse(int(cid))
                        self._last_info = info
            elif name == "accept_quest":
                # interact (loot corpse / talk to quest npc per obs.ts priority)
                obs, r, term, trunc, info = self.base.step(ACT_INTERACT)
            elif name == "turn_in_quest":
                # turn in via dedicated command (requires the quest to be ready
                # and the giver adjacent — server anti-bot, per adapter_v1 findings)
                q = next((q for q in (self._last_info.get("quests", {}).get("active") or [])
                          if q.get("ready") or q.get("state") in ("ready", "complete")), None)
                if q is not None:
                    info = self.base.turn_in_quest(str(q.get("id")))
                    self._last_info = info
                else:
                    obs, r, term, trunc, info = self.base.step(ACT_NOOP)
            elif name == "sell_junk":
                # server supports sellAllJunk() via the capability cmd (sells all
                # junk-quality items, credits copper) — real call, not a noop.
                info = self.base.sell_junk()
                self._last_info = info
            elif name == "gather":
                # harvest nearest harvestable node via dedicated command.
                nodes = [n for n in (self._last_info.get("gather", {}).get("nearbyNodes") or [])
                         if n.get("harvestable")]
                if nodes:
                    node = nodes[0]
                    info = self.base.harvest_node(str(node.get("id")), False)
                    self._last_info = info
                else:
                    obs, r, term, trunc, info = self.base.step(ACT_NOOP)
            elif name == "heal":
                # eat/drink to recover HP (noop if already full — sim ignores)
                obs, r, term, trunc, info = self.base.step(ACT_EAT_DRINK)
            elif name in ("equip", "buy"):
                # unsupported in headless: no inventory-equip / vendor-buy action in
                # obs.ts ACTIONS and no client worldApi surface. Honest noop.
                obs, r, term, trunc, info = self.base.step(ACT_NOOP)
            else:  # craft — unsupported in headless (sim.craft undefined in runtime)
                obs, r, term, trunc, info = self.base.step(ACT_NOOP)
            self._last_info = info
            if term or trunc:
                return self._reward_delta(info, q0, c0, k0), True

        info = self._last_info
        return self._reward_delta(info, q0, c0, k0), False

    def _reward_delta(self, info, q0, c0, k0) -> float:
        q1 = info.get("quests_done", 0)
        c1 = info.get("copper", 0)
        k1 = info.get("kills", 0)
        return (q1 - q0) * 5.0 + (c1 - c0) * 0.01 + (k1 - k0) * 0.2

    # ---- gym API ----
    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        if seed is not None:
            self.seed_base = seed
        obs, info = self.base.reset(seed=self.seed_base)
        self._last_info = info
        self._high_step = 0
        return self._hl_obs(info), info

    def step(self, action: int):
        self._high_step += 1
        reward, done = self._run_skill(int(action))
        info = self._last_info
        truncated = self._high_step >= self.max_high_steps
        terminated = bool(info.get("level", 1) >= 20)
        return self._hl_obs(info), float(reward), terminated, truncated, info

    def close(self):
        self.base.close()

    # ---- action masking (Phase D: keep PPO off unsupported/dead branches) ----
    def action_masks(self) -> np.ndarray:
        """Boolean mask over SKILLS. True = applicable in CURRENT world state.
        Based on PROVEN headless facts (see D:/woc-llm/memory.md Capability cmd
        surface): craft/equip/buy have NO server cmd -> always masked.
        sell_junk/gather/quest need world preconditions absent in headless spawn.
        """
        info = self._last_info or {}
        nearby = info.get("nearby") or []
        mobs = [e for e in nearby if (e.get("type") == "mob" or e.get("kind") == "mob")]
        corpses = [e for e in nearby
                   if (e.get("type") == "corpse" or e.get("kind") == "corpse"
                       or e.get("lootable")) and not e.get("looted")]
        quest_npcs = [e for e in nearby
                      if (e.get("kind") == "npc" or e.get("type") == "npc")
                      and (e.get("questIds") or e.get("questId"))]
        nodes = [n for n in (info.get("gather", {}).get("nearbyNodes") or [])
                 if n.get("harvestable")]
        ready_q = [q for q in (info.get("quests", {}).get("active") or [])
                   if q.get("ready") or q.get("state") in ("ready", "complete")]
        junk = [i for i in (info.get("inventory") or [])
                if (i.get("quality") or 0) == 0]

        mask = np.zeros(N_SKILLS, dtype=bool)
        mask[0] = bool(mobs) or info.get("targetId") is not None   # farm
        mask[1] = bool(corpses)                                    # loot
        mask[2] = bool(quest_npcs)                                 # accept_quest
        mask[3] = bool(ready_q)                                    # turn_in_quest
        mask[4] = bool(junk)                                       # sell_junk (vendor not observable)
        mask[5] = bool(nodes)                                      # gather
        mask[6] = False                                            # craft (no cmd)
        mask[7] = True                                             # heal (unconditional)
        mask[8] = False                                            # equip (no cmd)
        mask[9] = False                                            # buy (no cmd)
        return mask


def make_hl_env(**kwargs) -> HierarchicalWoWEnv:
    return HierarchicalWoWEnv(**kwargs)


if __name__ == "__main__":
    # smoke test: random high-level policy
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=50)
    obs, info = env.reset(seed=1)
    total = 0.0
    for _ in range(50):
        a = int(np.random.randint(N_SKILLS))
        obs, r, term, trunc, info = env.step(a)
        total += r
        if term or trunc:
            obs, info = env.reset(seed=1)
    print(f"hl random total reward: {total:.2f}")
    env.close()
