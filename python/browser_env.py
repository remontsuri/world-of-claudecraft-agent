"""browser_env.py — online WoC environment adapter for the Python Agent.

Implements the SAME interface HierarchicalWoWEnv exposes to Agent/quest_skill:
  - reset(seed)              -> sets self._last_info
  - step(idx)                -> apply one low-level skill action, refresh _last_info
  - _last_info               -> flat info dict (build_world_state-compatible)
  - _navigate_to_coord(x,z)  -> walk to a world coord (used by return_to_giver)
  - close()

The actual world is the LIVE browser tab driven by browser_bridge.cjs over CDP.
This module is pure I/O: it posts actions to the bridge and reads observations
back. All learning (policy/memory/reward) stays in agent.py / memory.py / reward.py.

No reward logic, no Sim edits, no PPO here.
"""

import json
import urllib.request
import urllib.error

BRIDGE_URL = "http://127.0.0.1:8791"

# skill indices MUST match hierarchical_env.SKILLS order so Agent's SKILL_INDEX
# mapping stays valid:
# 0 farm, 1 loot, 2 accept_quest, 3 turn_in_quest, 4 sell_junk,
# 5 gather, 6 craft, 7 heal, 8 equip, 9 buy
ACT_FORWARD = 1
ACT_TURN_LEFT = 3
ACT_TURN_RIGHT = 4


class BrowserEnv:
    """Online world proxy. One instance = one live character session."""

    def __init__(self, player_class: str = "warrior", max_steps: int = 100000, seed: int = 0):
        self.player_class = player_class
        self.max_steps = max_steps
        self.seed = seed
        self._last_info = None
        self._step = 0
        self.base = BrowserBase(self)  # quest_skill uses env.base.step(ACT_FORWARD) for explore
        # prime: fetch an initial observation so _last_info is never None
        self._last_info = self._require({"action": "snapshot"}).get("info", {})

    # ---- bridge I/O ----
    def _post(self, payload: dict, timeout: float = 30.0) -> dict:
        """POST to the bridge and return the parsed response. The caller is
        responsible for treating ok:false as a real failure (see _require)."""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            BRIDGE_URL, data=data, headers={"content-type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _require(self, payload: dict, timeout: float = 30.0) -> dict:
        """POST and raise RuntimeError on ok:false so the Agent records ENV_ERROR
        (reward 0, memory untouched) instead of learning from an empty snapshot.
        Used by every read/write path — no silent stop()/empty-info fallback."""
        resp = self._post(payload, timeout=timeout)
        if not resp.get("ok", False):
            raise RuntimeError(f"bridge {payload.get('action')} failed: {resp.get('error')}")
        return resp

    # ---- gym-style interface used by Agent ----
    def reset(self, seed: int = None):
        if seed is not None:
            self.seed = seed
        # if the character is dead on entry, respawn so the loop can start clean
        resp = self._post({"action": "snapshot"})
        if not resp.get("ok", False):
            raise RuntimeError(f"bridge reset failed: {resp.get('error')}")
        info = resp.get("info", {})
        if info.get("player", {}).get("dead"):
            self._require({"action": "respawn"})
            resp = self._require({"action": "snapshot"})
            if not resp.get("ok", False):
                raise RuntimeError(f"bridge respawn+snapshot failed: {resp.get('error')}")
            info = self._last_info = resp.get("info", {})
        else:
            self._last_info = info
        self._step = 0
        return None, info

    def step(self, idx: int):
        """Apply one skill action (idx). Returns (obs, reward, done, truncated, info)
        like gym, but Agent only uses _last_info + the returned info.

        An `ok:false` from the bridge is an infrastructure failure, NOT a game
        outcome — raise so the Agent records ENV_ERROR (reward 0, memory untouched)
        instead of treating the empty `info` as a real world state and learning a
        false lesson.
        """
        resp = self._post({"action": "step", "idx": int(idx)})
        if not resp.get("ok", False):
            raise RuntimeError(f"bridge step failed: {resp.get('error')}")
        info = resp.get("info", {})
        self._last_info = info
        self._step += 1
        done = bool(info.get("player", {}).get("dead"))
        return None, 0.0, done, False, info

    def _navigate_to_coord(self, tx: float, tz: float, max_steps: int = 80, timeout: float = 90.0) -> bool:
        """Walk to (tx,tz). Returns True if arrived. Used by return_to_giver.

        `timeout` must exceed max_steps*0.22s (bridge sleeps TICK_MS per step and
        answers only AFTER the full walk loop — it blocks the HTTP response)."""
        resp = self._require({"action": "navigate", "x": tx, "z": tz, "max_steps": max_steps}, timeout=timeout)
        info = resp.get("info", {})
        self._last_info = info
        return bool(resp.get("arrived"))

    def _raw_move(self, kind: str):
        """Send a single raw movement through the bridge (forward/back/turnLeft/
        turnRight/stop). Used by BrowserBase for explore/ACT_* actions."""
        resp = self._require({"action": "raw_move", "kind": kind})
        info = resp.get("info", {})
        self._last_info = info
        return info

    def respawn(self):
        """Release spirit + resurrect at healer (online-safe glue; does NOT mutate
        the model). Call when the character is dead so the loop can continue."""
        resp = self._require({"action": "respawn"})
        info = resp.get("info", {})
        self._last_info = info
        return info

    def explore_walk(self, steps: int = 10):
        """Sustained exploration: walk toward nearest mob/NPC (or forward) for
        `steps` ticks. Lets the agent actually traverse the world instead of
        jittering in place. Used by Agent for the `explore` skill."""
        resp = self._require({"action": "explore", "steps": steps})
        info = resp.get("info", {})
        self._last_info = info
        return bool(resp.get("arrived"))

    def close(self):
        # bridge (node process) keeps running; nothing to tear down here.
        pass

    # compatibility shims used by some diagnostic scripts / quest_skill
    def base_step(self, idx: int):
        return self.step(idx)


class BrowserBase:
    """Low-level action interface (ACT_* indices) for quest_skill.explore.

    quest_skill calls env.base.step(ACT_FORWARD) — that is a raw movement
    action (ACT_FORWARD=1), NOT a high-level skill. We map ACT_* here so explore
    actually walks forward instead of being interpreted as the 'loot' skill.
    """

    def __init__(self, env: "BrowserEnv"):
        self.env = env

    def step(self, idx: int):
        # ACT_* from hierarchical_env: 0 noop, 1 forward, 2 back, 3 turn_left,
        # 4 turn_right, 6 strafe_right, 8 target_nearest, 9 attack
        if idx == 1:      # forward
            self.env._raw_move("forward")
        elif idx == 2:    # back
            self.env._raw_move("back")
        elif idx == 3:    # turn_left
            self.env._raw_move("turnLeft")
        elif idx == 4:    # turn_right
            self.env._raw_move("turnRight")
        else:
            self.env._raw_move("stop")
        return None, 0.0, False, False, self.env._last_info
