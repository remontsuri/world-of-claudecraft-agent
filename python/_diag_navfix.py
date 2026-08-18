"""READ-ONLY verification: corrected bearing formula + realistic alignment gate.

_diag_nav3 ground truth: heading vector == (sin(facing), cos(facing)), so the
correct bearing is atan2(dx, dz). hierarchical_env._navigate_to_coord uses
atan2(dx, -dz) -> Z sign inverted -> walks away from the target.
Also facing is quantized to 45 deg, so the |off|<=4 gate is unreachable.

This script does NOT edit hierarchical_env. It implements a corrected local nav
and compares three variants head-to-head on the SAME start state:
   V0: current code    (atan2(dx,-dz), gate 4 deg)
   V1: fixed bearing   (atan2(dx, dz),  gate 4 deg)
   V2: fixed + gate    (atan2(dx, dz),  gate 22.5 deg)
Reported: distance closed, arrival, steps used.

Also measures targetOffDeg convention (used by _navigate_to_target for farm).
"""

import math
import sys

from hierarchical_env import (HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT,
                              ACT_TURN_RIGHT, ACT_STRAFE_RIGHT, ACT_TARGET_NEAREST)

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
DEG = 180.0 / math.pi
ACT_STOP = 59
TX, TZ = 4.5, 5.5  # marshal_redbrook


def step(env, a):
    _, _, _, _, info = env.base.step(a)
    env._last_info = info
    return info


def pos(env):
    p = env._last_info.get("player_pos")
    return (p[0], p[1])


def dist_to(env, tx=TX, tz=TZ):
    px, pz = pos(env)
    return math.hypot(tx - px, tz - pz)


def nav(env, tx, tz, max_steps, flip_z: bool, gate: float):
    """One nav variant. flip_z=True reproduces the current (buggy) formula."""
    best = None
    no_progress = 0
    steps = 0
    last_pos = None
    stuck = 0
    for _ in range(max_steps):
        steps += 1
        px, pz = pos(env)
        dx, dz = tx - px, tz - pz
        d = math.hypot(dx, dz)
        if d < 5:
            return True, steps
        if best is None or d < best - 0.5:
            best = d
            no_progress = 0
        else:
            no_progress += 1
            if no_progress >= 30:
                return False, steps
        want = DEG * (math.atan2(dx, -dz) if flip_z else math.atan2(dx, dz))
        facing = (env._last_info.get("facing") or 0.0) * DEG
        off = ((want - facing + 180.0) % 360.0) - 180.0
        if abs(off) > gate:
            step(env, ACT_TURN_RIGHT if off > 0 else ACT_TURN_LEFT)
            continue
        step(env, ACT_FORWARD)
        p = pos(env)
        if last_pos is not None and abs(p[0] - last_pos[0]) < 0.3 and abs(p[1] - last_pos[1]) < 0.3:
            stuck += 1
            if stuck >= 3:
                step(env, ACT_STRAFE_RIGHT)
                step(env, ACT_TURN_RIGHT)
                stuck = 0
        else:
            stuck = 0
        last_pos = p
    return False, steps


def walk_away(env, target_dist=100.0, max_steps=400):
    """Harness-level drift: walk until far from the giver. Not a policy action."""
    for _ in range(max_steps):
        if dist_to(env) >= target_dist:
            return True
        step(env, ACT_FORWARD)
    return dist_to(env) >= target_dist


def run_variant(name, flip_z, gate, seed):
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=seed)
    env.reset(seed=seed)
    walk_away(env, 100.0)
    d0 = dist_to(env)
    ok, steps = nav(env, TX, TZ, 300, flip_z=flip_z, gate=gate)
    d1 = dist_to(env)
    env.close()
    print(f"  {name:34s} dist {d0:7.1f} -> {d1:7.1f}  closed={d0 - d1:+8.1f}  "
          f"arrived={ok}  steps={steps}")
    return d0 - d1


def main():
    print(f"=== NAV FIX VERIFY seed={SEED} ===")
    print("\n--- A/B/C: identical start state, three nav variants ---")
    c0 = run_variant("V0 current  atan2(dx,-dz) g=4", True, 4.0, SEED)
    c1 = run_variant("V1 fixed    atan2(dx, dz) g=4", False, 4.0, SEED)
    c2 = run_variant("V2 fixed    atan2(dx, dz) g=22.5", False, 22.5, SEED)

    print("\n--- VERDICT ---")
    print(f"  V0 closed {c0:+.1f} | V1 closed {c1:+.1f} | V2 closed {c2:+.1f}")
    best = max([(c0, "V0"), (c1, "V1"), (c2, "V2")])
    print(f"  BEST: {best[1]}")

    # ---- targetOffDeg convention (used by farm's _navigate_to_target) ----
    print("\n--- targetOffDeg convention (farm path) ---")
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=SEED)
    env.reset(seed=SEED)
    step(env, ACT_TARGET_NEAREST)
    for i in range(10):
        info = env._last_info
        off = info.get("targetOffDeg")
        td = info.get("targetDist")
        if off is None:
            step(env, ACT_TARGET_NEAREST)
            continue
        a = ACT_TURN_RIGHT if off > 0 else ACT_TURN_LEFT
        step(env, a)
        off2 = env._last_info.get("targetOffDeg")
        td2 = env._last_info.get("targetDist")
        if off2 is None:
            print(f"  [{i}] off={off:+.1f} -> target lost")
            continue
        print(f"  [{i}] turn{'R' if off > 0 else 'L'}: off {off:+7.1f}->{off2:+7.1f} "
              f"|off| {'DOWN' if abs(off2) < abs(off) else 'UP  '}  dist {td}->{td2}")
    env.close()
    print("\n=== NAV FIX VERIFY END ===")


if __name__ == "__main__":
    main()
