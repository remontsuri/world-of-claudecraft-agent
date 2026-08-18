"""READ-ONLY: farm navigation + nearby entity fields.

_navigate_to_target trusts the server's `targetOffDeg`, computed in
dist-env/env_server.cjs:128480 as  atan2(dx, -dz) - facing.
But the sim's own documented convention (src/sim/player_motion.ts:286) is that
facing points along (sin f, cos f), i.e. the true bearing is atan2(dx, dz).
Since atan2(dx,-dz) == norm(180 - atan2(dx,dz)), targetOffDeg is NOT the true
off-angle and turning by its sign need not reduce it.

Measured here:
  F1. nearby entity field names (do we get x/z per mob? -> can we self-compute?)
  F2. does turning by sign(targetOffDeg) reduce |targetOffDeg| and targetDist?
  F3. does turning by sign(off_true), computed from the mob's own x/z, work?
  F4. head-to-head: current _navigate_to_target vs corrected bearing, same seed,
      measured by "did targetDist drop below melee (8)".
"""

import json
import math
import sys

from hierarchical_env import (HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT,
                              ACT_TURN_RIGHT, ACT_TARGET_NEAREST, ACT_STRAFE_RIGHT)

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
DEG = 180.0 / math.pi


def step(env, a):
    _, _, _, _, info = env.base.step(a)
    env._last_info = info
    return info


def main():
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=SEED)
    env.reset(seed=SEED)
    print(f"=== FARM NAV DIAG seed={SEED} ===")

    # ---- F1: nearby entity fields ----
    print("\n--- F1: nearby entity structure ---")
    near = env._last_info.get("nearby") or []
    print(f"  nearby count: {len(near)}")
    for e in near[:3]:
        print(f"  entry: {json.dumps(e, ensure_ascii=False)[:260]}")
    if near:
        print(f"  field names: {sorted(near[0].keys())}")
        has_xz = all(("x" in e and "z" in e) for e in near[:5])
        print(f"  >> all entries carry x/z: {has_xz}")

    # ---- F2: turning by sign(targetOffDeg) ----
    print("\n--- F2: turn by sign(targetOffDeg) ---")
    step(env, ACT_TARGET_NEAREST)
    tid = env._last_info.get("targetId")
    print(f"  targetId={tid} targetDist={env._last_info.get('targetDist')} "
          f"targetOffDeg={env._last_info.get('targetOffDeg')}")
    for i in range(8):
        info = env._last_info
        off = info.get("targetOffDeg")
        td = info.get("targetDist")
        if off is None:
            step(env, ACT_TARGET_NEAREST)
            continue
        step(env, ACT_TURN_RIGHT if off > 0 else ACT_TURN_LEFT)
        off2 = env._last_info.get("targetOffDeg")
        td2 = env._last_info.get("targetDist")
        if off2 is None or td2 is None:
            print(f"  [{i}] target lost")
            break
        print(f"  [{i}] turn{'R' if off > 0 else 'L'} off {off:+7.1f}->{off2:+7.1f} "
              f"|off|{'DOWN' if abs(off2) < abs(off) else 'UP  '}  dist {td:6.2f}->{td2:6.2f}")

    # ---- F3: turning by self-computed true bearing ----
    print("\n--- F3: turn by sign(off_true) from mob x/z (atan2(dx,dz)) ---")
    env2 = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=SEED)
    env2.reset(seed=SEED)
    step(env2, ACT_TARGET_NEAREST)

    def true_off(e2):
        info = e2._last_info
        tid = info.get("targetId")
        if tid is None:
            return None, None
        ent = None
        for x in (info.get("nearby") or []):
            if x.get("id") == tid:
                ent = x
                break
        if ent is None or ent.get("x") is None:
            return None, info.get("targetDist")
        px, pz = info.get("player_pos", [0, 0])
        dx, dz = ent["x"] - px, ent["z"] - pz
        want = DEG * math.atan2(dx, dz)
        facing = (info.get("facing") or 0.0) * DEG
        return ((want - facing + 180) % 360) - 180, math.hypot(dx, dz)

    for i in range(8):
        off, td = true_off(env2)
        if off is None:
            step(env2, ACT_TARGET_NEAREST)
            print(f"  [{i}] no bearing (targetDist={td})")
            continue
        # source: turn_right DECREASES facing -> to raise facing (off>0) turn LEFT
        step(env2, ACT_TURN_LEFT if off > 0 else ACT_TURN_RIGHT)
        off2, td2 = true_off(env2)
        if off2 is None:
            print(f"  [{i}] target lost")
            break
        print(f"  [{i}] turn{'L' if off > 0 else 'R'} off {off:+7.1f}->{off2:+7.1f} "
              f"|off|{'DOWN' if abs(off2) < abs(off) else 'UP  '}  dist {td:6.2f}->{td2:6.2f}")
    env2.close()

    # ---- F4: head to head, reach melee? ----
    print("\n--- F4: reach melee (<8) — current vs corrected ---")

    def run_current(seed):
        e = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=seed)
        e.reset(seed=seed)
        step(e, ACT_TARGET_NEAREST)
        d0 = e._last_info.get("targetDist")
        ok = e._navigate_to_target(max_steps=60)
        d1 = e._last_info.get("targetDist")
        e.close()
        return d0, d1, ok

    def run_fixed(seed):
        e = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=seed)
        e.reset(seed=seed)
        step(e, ACT_TARGET_NEAREST)
        d0 = e._last_info.get("targetDist")
        last = None
        stuck = 0
        reached = False
        for _ in range(60):
            info = e._last_info
            tid = info.get("targetId")
            if tid is None:
                step(e, ACT_TARGET_NEAREST)
                continue
            ent = next((x for x in (info.get("nearby") or []) if x.get("id") == tid), None)
            td = info.get("targetDist")
            if td is not None and td < 8:
                reached = True
                break
            if ent is None or ent.get("x") is None:
                step(e, ACT_TARGET_NEAREST)
                continue
            px, pz = info.get("player_pos", [0, 0])
            dx, dz = ent["x"] - px, ent["z"] - pz
            want = DEG * math.atan2(dx, dz)
            facing = (info.get("facing") or 0.0) * DEG
            off = ((want - facing + 180) % 360) - 180
            if abs(off) > 22.5:
                step(e, ACT_TURN_LEFT if off > 0 else ACT_TURN_RIGHT)
                continue
            step(e, ACT_FORWARD)
            p = info.get("player_pos")
            if last and abs(p[0] - last[0]) < 0.3 and abs(p[1] - last[1]) < 0.3:
                stuck += 1
                if stuck >= 3:
                    step(e, ACT_STRAFE_RIGHT)
                    step(e, ACT_TURN_RIGHT)
                    stuck = 0
            else:
                stuck = 0
            last = p
        d1 = e._last_info.get("targetDist")
        e.close()
        return d0, d1, reached

    for s in (42, 107, 256):
        a = run_current(s)
        b = run_fixed(s)
        print(f"  seed {s}: current dist {a[0]} -> {a[1]} melee={a[2]}   |   "
              f"fixed dist {b[0]} -> {b[1]} melee={b[2]}")

    env.close()
    print("\n=== END ===")


if __name__ == "__main__":
    main()
