"""play_fly_live.py — live PPO fly controller with closed-loop navigation.

The offline PPO only learns WHAT high-level skill to choose.  This adapter supplies
the missing motor layer for the real game:
  PPO -> target selection -> short navigation -> skill execution -> verification.

It never changes the game simulation.  Navigation is closed-loop: every segment
re-reads player position/facing and stops when progress stalls.
"""
import math
import time
import numpy as np
from stable_baselines3 import PPO

from python.woc_game import WoCGameClient


class LiveFly:
    def __init__(self, host="127.0.0.1", port=8791, model_path="data/ppo_fly_offline"):
        self.game = WoCGameClient(host, port)
        self.model = PPO.load(model_path)
        self.last_pos = None
        self.anchor = None
        self.explore_i = 0
        self.quest_giver = None

    @staticmethod
    def _dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    @staticmethod
    def _angle_to(dx, dz):
        # WoC facing=0 looks toward -Z.
        return math.atan2(dx, -dz)

    @staticmethod
    def _angle_diff(a, b):
        return (a - b + math.pi) % (2 * math.pi) - math.pi

    def snapshot(self):
        return self.game.snapshot()

    def encode(self, info):
        player = info.get("player", {})
        pos = info.get("player_pos", [0.0, 0.0])
        nearby = info.get("nearby", []) or []
        mobs = [e for e in nearby
                if e.get("kind") == "mob"
                and e.get("hostile", True)
                and not e.get("dead", False)]
        npcs = [e for e in nearby if e.get("kind") == "npc"]
        loot = [e for e in nearby if e.get("lootable") and not e.get("looted", False)]

        mob = min(mobs, key=lambda e: e.get("dist", 999.0), default=None)
        npc_q = [e for e in npcs if e.get("questIds") or e.get("questId")]
        npc = min(npc_q or npcs, key=lambda e: e.get("dist", 999.0), default=None)
        item = min(loot, key=lambda e: e.get("dist", 999.0), default=None)

        quests = info.get("quests", {}) or {}
        active = quests.get("active", []) or []

        # Keep the live encoder compatible with train_ppo_offline.py:
        # exactly the same 16 semantic slots and scaling.
        nearest_hostile_dist = mob.get("dist", 100.0) if mob else 100.0
        nearest_npc_dist = npc.get("dist", 100.0) if npc else 100.0
        return np.asarray([
            pos[0] / 1000.0,
            pos[1] / 1000.0,
            player.get("hp", 100.0) / max(player.get("maxHp", 100.0), 1.0),
            player.get("maxHp", 100.0) / 100.0,
            nearest_hostile_dist / 100.0,
            0.5,
            nearest_npc_dist / 100.0,
            0.5,
            0.5,
            (info.get("tick", 0) % 1000) / 1000.0,
            1.0 if active else 0.0,
            min(len(active), 10) / 10.0,
            min(len(info.get("inventory", []) or []), 64) / 64.0,
            min(info.get("copper", 0), 10000) / 10000.0,
            1.0 if player.get("inCombat", False) else 0.0,
            info.get("kills", 0) / 100.0,
        ], dtype=np.float32)

    def _turn_and_move(self, tx, tz, max_steps=18, arrive=4.5):
        """Short closed-loop segment. Re-observe after every motor command."""
        start = self.snapshot()
        if not start:
            return False

        last_distance = None
        stagnant = 0

        for _ in range(max_steps):
            info = self.snapshot()
            if not info:
                return False
            pos = info.get("player_pos", [0.0, 0.0])
            player = info.get("player", {}) or {}
            dist = self._dist(pos, (tx, tz))
            if dist <= arrive:
                return True

            facing = float(player.get("facing", 0.0))
            desired = self._angle_to(tx - pos[0], tz - pos[1])
            diff = self._angle_diff(desired, facing)

            # Deadband must exceed half the per-call turn rate (~0.63 rad)
            # to prevent left/right oscillation.
            if abs(diff) > 1.0:
                kind = "turnRight" if diff > 0 else "turnLeft"
                self.game.raw_move(kind)
            else:
                self.game.raw_move("forward")

            time.sleep(0.08)

            after = self.snapshot()
            if after:
                p2 = after.get("player_pos", pos)
                d2 = self._dist(p2, (tx, tz))
                if last_distance is not None and d2 >= last_distance - 0.05:
                    stagnant += 1
                else:
                    stagnant = 0
                last_distance = d2
                if stagnant >= 4:
                    return False

        return False

    def _remember_giver(self, info):
        npcs = [e for e in info.get("nearby", []) or []
                if e.get("kind") == "npc"
                and (e.get("questIds") or e.get("questId"))]
        if npcs:
            self.quest_giver = min(npcs, key=lambda e: e.get("dist", 999.0))

    def _target_for_action(self, action, info):
        nearby = info.get("nearby", []) or []

        if action == 0:
            xs = [e for e in nearby if e.get("kind") == "mob"
                  and e.get("hostile", True) and not e.get("dead", False)]
            return min(xs, key=lambda e: e.get("dist", 999.0), default=None)

        if action == 1:
            xs = [e for e in nearby if e.get("lootable") and not e.get("looted", False)]
            return min(xs, key=lambda e: e.get("dist", 999.0), default=None)

        if action == 2:
            xs = [e for e in nearby if e.get("kind") == "npc"
                  and (e.get("questIds") or e.get("questId"))]
            target = min(xs, key=lambda e: e.get("dist", 999.0), default=None)
            if target:
                self.quest_giver = target
            return target

        if action == 3:
            if self.quest_giver:
                # Refresh the remembered NPC from nearby when possible.
                for e in nearby:
                    if e.get("kind") == "npc" and e.get("id") == self.quest_giver.get("id"):
                        self.quest_giver = e
                        break
                return self.quest_giver
            xs = [e for e in nearby if e.get("kind") == "npc"]
            return min(xs, key=lambda e: e.get("dist", 999.0), default=None)

        if action == 4:
            xs = [e for e in nearby if e.get("kind") == "npc" and e.get("vendor", False)]
            return min(xs, key=lambda e: e.get("dist", 999.0), default=None)

        return None

    def explore(self, info):
        """Search beyond the ~40yd local entity window using short waypoints."""
        pos = info.get("player_pos", [0.0, 0.0])
        if self.anchor is None or self._dist(pos, self.anchor) > 70:
            self.anchor = list(pos)
            self.explore_i = 0

        # Four directions, then expand. This gives deterministic coverage without
        # teleporting or changing simulation logic.
        ring = self.explore_i // 4 + 1
        dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        dx, dz = dirs[self.explore_i % 4]
        radius = min(12.0 * ring, 60.0)
        target = (self.anchor[0] + dx * radius, self.anchor[1] + dz * radius)
        self.explore_i += 1

        self._turn_and_move(target[0], target[1], max_steps=12, arrive=5.0)

    def run(self, steps=500, delay=0.12):
        print("[fly] loading live controller")
        info = self.snapshot()
        if not info:
            raise RuntimeError("bridge is not responding")

        print("[fly] bridge OK")
        for i in range(steps):
            info = self.snapshot()
            if not info:
                time.sleep(0.5)
                continue

            player = info.get("player", {}) or {}
            hp = float(player.get("hp", 0))
            max_hp = max(float(player.get("maxHp", 100)), 1.0)

            if hp <= 0 or player.get("dead", False):
                print(f"[{i}] DEAD -> respawn")
                self.game.respawn()
                time.sleep(1.0)
                continue

            self._remember_giver(info)

            # Hard safety layer: do not let PPO walk into a death spiral.
            if hp / max_hp < 0.25:
                self.game.raw_move("back")
                time.sleep(0.12)
                continue

            obs = self.encode(info)
            action, _ = self.model.predict(obs, deterministic=True)
            action = int(np.asarray(action).reshape(-1)[0])

            target = self._target_for_action(action, info)

            if target and target.get("x") is not None and target.get("z") is not None:
                dist = float(target.get("dist", 999.0))
                if dist > (4.5 if action in (0, 1) else 5.5):
                    arrived = self._turn_and_move(
                        float(target["x"]), float(target["z"]),
                        max_steps=18,
                        arrive=4.5 if action in (0, 1) else 5.5,
                    )
                    info2 = self.snapshot()
                    if info2:
                        target2 = self._target_for_action(action, info2)
                        if target2:
                            target = target2

                # Execute only after reaching interaction/attack range.
                if action == 0:
                    tdist = float(target.get("dist", 999.0))
                    if tdist <= 7.0:
                        result = self.game.step(0)
                    else:
                        result = info
                else:
                    result = self.game.step(action)
            else:
                # Critical fix for the live/offline mismatch: if PPO requests a
                # skill but the entity is outside the observation window, search
                # instead of repeatedly issuing a no-op.
                self.explore(info)
                result = self.snapshot()

            if i % 10 == 0:
                p = result.get("player", {}) if result else {}
                print(
                    f"[{i:4d}] ppo={action} hp={p.get('hp', 0):.0f} "
                    f"kills={result.get('kills', 0) if result else 0} "
                    f"qdone={result.get('quests_done', 0) if result else 0} "
                    f"pos={(result.get('player_pos') if result else None)}"
                )
            time.sleep(delay)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--model", default="data/ppo_fly_offline")
    args = parser.parse_args()
    LiveFly(args.host, args.port, args.model).run(args.steps)
