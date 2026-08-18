"""READ-ONLY diagnostic: is _navigate_to_coord's bearing math correct?

Q3 of _diag_return.py showed return_to_giver INCREASING distance (19.2 -> 31.6)
and then dithering +-0.5 around 31. Before touching reward, prove whether the
navigation primitive can close distance at all.

Measured, per low-level step:
  want (bearing to target), facing, off, action taken, dist before/after.
If `forward` with |off|<4 does not reduce dist, the bearing frame is wrong.
If turn does not reduce |off|, the turn direction is inverted.

No memory, no policy, no Sim edits.
"""

import math
import sys

from hierarchical_env import (HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT,
                              ACT_TURN_RIGHT)
from quest_capability import QuestCapability

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
DEG = 180.0 / math.pi


def accept_welcome(env):
    cap = QuestCapability(env)
    if cap.find_active_quest() is not None:
        return True
    for _ in range(24):
        env.base.step(ACT_FORWARD)
        env.base.step(ACT_TURN_LEFT)
        near = env._last_info.get("nearby") or []
        g = [e for e in near if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
        if g:
            qid = (g[0].get("questIds") or [None])[0]
            env._navigate_to_coord(g[0].get("x"), g[0].get("z"), max_steps=80)
            env.base.accept_quest(str(qid))
            env._last_info = env.base.accept_quest(str(qid))
            return True
    return False


def geom(info, tx, tz):
    px, pz = info.get("player_pos", [0, 0])
    dx, dz = tx - px, tz - pz
    dist = (dx * dx + dz * dz) ** 0.5
    want = DEG * math.atan2(dx, -dz)
    facing = (info.get("facing") or 0.0) * DEG
    off = ((want - facing + 180.0) % 360.0) - 180.0
    return dist, want, facing, off


def main():
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=SEED)
    env.reset(seed=SEED)
    accept_welcome(env)

    # walk away from spawn so there is a real distance to close
    for _ in range(40):
        env.base.step(ACT_FORWARD)
    info = env._last_info
    print(f"=== NAV DIAG seed={SEED} ===")
    print(f"raw info keys: {sorted(info.keys())}")
    print(f"facing raw={info.get('facing')}  player_pos={info.get('player_pos')}")

    TX, TZ = 4.5, 5.5  # marshal_redbrook (turn-in NPC)

    # --- Test 1: does turn_right reduce |off|? (direction convention) ---
    print("\n--- T1: turn convention (8x turn_right, watch off) ---")
    for i in range(8):
        d, want, facing, off = geom(env._last_info, TX, TZ)
        _, _, _, _, info = env.base.step(ACT_TURN_RIGHT)
        env._last_info = info
        d2, want2, facing2, off2 = geom(info, TX, TZ)
        print(f"  turnR[{i}] facing {facing:+7.1f}->{facing2:+7.1f}  "
              f"off {off:+7.1f}->{off2:+7.1f}  |off| {'DOWN' if abs(off2) < abs(off) else 'UP'}")

    # --- Test 2: does forward reduce dist when |off| is small? ---
    print("\n--- T2: align then forward (aim <=4deg, then 15x forward) ---")
    for _ in range(120):
        d, want, facing, off = geom(env._last_info, TX, TZ)
        if abs(off) <= 4:
            break
        _, _, _, _, info = env.base.step(ACT_TURN_RIGHT if off > 0 else ACT_TURN_LEFT)
        env._last_info = info
    d, want, facing, off = geom(env._last_info, TX, TZ)
    print(f"  aligned: dist={d:.1f} want={want:+.1f} facing={facing:+.1f} off={off:+.1f}")
    for i in range(15):
        d0, _, _, off0 = geom(env._last_info, TX, TZ)
        p0 = env._last_info.get("player_pos")
        _, _, _, _, info = env.base.step(ACT_FORWARD)
        env._last_info = info
        d1, _, f1, off1 = geom(info, TX, TZ)
        p1 = info.get("player_pos")
        moved = ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5
        print(f"  fwd[{i:2d}] dist {d0:6.2f}->{d1:6.2f} ({d0 - d1:+.2f})  "
              f"off {off0:+6.1f}->{off1:+6.1f}  moved={moved:.2f}")

    # --- Test 3: full _navigate_to_coord, report honest outcome ---
    print("\n--- T3: _navigate_to_coord(4.5, 5.5, max_steps=80) ---")
    d0, _, _, _ = geom(env._last_info, TX, TZ)
    ok = env._navigate_to_coord(TX, TZ, max_steps=80)
    d1, _, _, _ = geom(env._last_info, TX, TZ)
    print(f"  returned={ok}  dist {d0:.2f} -> {d1:.2f} (delta={d0 - d1:+.2f})")
    print(f"  pos={env._last_info.get('player_pos')}")

    env.close()
    print("\n=== NAV DIAG END ===")


if __name__ == "__main__":
    main()
