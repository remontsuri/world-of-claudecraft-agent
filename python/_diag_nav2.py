"""READ-ONLY diagnostic: facing quantization + movement inertia.

_diag_nav T2 showed the align-loop EXITING with off=+135 deg (never reached the
|off|<=4 gate) and forward then INCREASING distance. Two candidate causes:

  T4. facing is QUANTIZED (45 deg steps?) -> the |off|<=4 gate in
      _navigate_to_coord is unreachable for most bearings -> the primitive spins
      forever and never presses forward.
  T5. movement is a CONTINUOUS flag, not an impulse -> the character keeps
      walking while we turn, so the bearing target drifts under us. If so, a
      stop (ACTION 59) is required before/while turning.
  T6. is ACTION 59 ("stop") actually present in the action list, and does it
      halt the character?

No memory, no policy, no Sim edits. Pure measurement.
"""

import math
import sys

from hierarchical_env import (HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT,
                              ACT_TURN_RIGHT, ACT_NOOP)

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
DEG = 180.0 / math.pi
ACT_STOP = 59


def pos(env):
    return env._last_info.get("player_pos")


def facing_deg(env):
    return (env._last_info.get("facing") or 0.0) * DEG


def step(env, a):
    _, _, _, _, info = env.base.step(a)
    env._last_info = info
    return info


def dist(p0, p1):
    return ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5


def main():
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=3000, seed=SEED)
    env.reset(seed=SEED)

    print(f"=== NAV DIAG 2  seed={SEED} ===")
    print(f"action list ({len(env.base.action_names)}): "
          f"...58={env.base.action_names[58]!r} 59={env.base.action_names[59]!r} "
          f"60={env.base.action_names[60]!r}")

    # ---- T4: facing quantization ----
    print("\n--- T4: facing values over 16x turn_left (is it quantized?) ---")
    vals = []
    for i in range(16):
        step(env, ACT_TURN_LEFT)
        vals.append(round(facing_deg(env), 3))
    print(f"  facings: {vals}")
    uniq = sorted(set(vals))
    print(f"  distinct: {uniq}")
    diffs = sorted({round(abs(((b - a + 180) % 360) - 180), 3) for a, b in zip(vals, vals[1:])})
    print(f"  step sizes: {diffs}")
    print(f"  >> quantized to ~45 deg? {all(abs(d - 45.0) < 1.0 or d < 1e-6 for d in diffs)}")
    print(f"     If yes: the |off|<=4 gate in _navigate_to_coord is UNREACHABLE")
    print(f"     for most bearings -> primitive spins, never walks.")

    # ---- T5: is movement continuous (inertia) or impulse? ----
    print("\n--- T5: movement inertia (1x forward, then 6x noop) ---")
    p0 = pos(env)
    step(env, ACT_FORWARD)
    p1 = pos(env)
    print(f"  forward     : moved {dist(p0, p1):.3f}  pos {p1}")
    for i in range(6):
        pa = pos(env)
        step(env, ACT_NOOP)
        pb = pos(env)
        print(f"  noop[{i}]     : moved {dist(pa, pb):.3f}  pos {pb}")
    print("  >> if noop keeps moving: movement is a CONTINUOUS flag (inertia).")

    # ---- T6: does ACTION 59 (stop) halt the character? ----
    print("\n--- T6: stop(59) after forward ---")
    step(env, ACT_FORWARD)
    step(env, ACT_FORWARD)
    pa = pos(env)
    step(env, ACT_STOP)
    pb = pos(env)
    print(f"  stop        : moved {dist(pa, pb):.3f}")
    for i in range(4):
        pc = pos(env)
        step(env, ACT_NOOP)
        pd = pos(env)
        print(f"  noop[{i}]     : moved {dist(pc, pd):.3f}")
    print("  >> if these are ~0: stop(59) works and MUST be used before turning.")

    # ---- T7: turn while stopped — does off change predictably? ----
    print("\n--- T7: turn direction convention while STOPPED (target 4.5,5.5) ---")
    TX, TZ = 4.5, 5.5
    step(env, ACT_STOP)
    for i in range(8):
        px, pz = pos(env)
        want = DEG * math.atan2(TX - px, -(TZ - pz))
        f0 = facing_deg(env)
        off0 = ((want - f0 + 180) % 360) - 180
        step(env, ACT_TURN_RIGHT)
        f1 = facing_deg(env)
        px2, pz2 = pos(env)
        want2 = DEG * math.atan2(TX - px2, -(TZ - pz2))
        off1 = ((want2 - f1 + 180) % 360) - 180
        print(f"  turnR[{i}] facing {f0:+7.1f}->{f1:+7.1f}  off {off0:+7.1f}->{off1:+7.1f} "
              f"|off| {'DOWN' if abs(off1) < abs(off0) else 'UP  '}  drift={dist((px,pz),(px2,pz2)):.3f}")

    # ---- T8: aligned-forward with a REALISTIC gate (<=25 deg) ----
    print("\n--- T8: align to <=25deg (half of 45 quantum) then walk 12x ---")
    for _ in range(40):
        px, pz = pos(env)
        want = DEG * math.atan2(TX - px, -(TZ - pz))
        off = ((want - facing_deg(env) + 180) % 360) - 180
        if abs(off) <= 25:
            break
        step(env, ACT_TURN_RIGHT if off > 0 else ACT_TURN_LEFT)
    px, pz = pos(env)
    d0 = ((TX - px) ** 2 + (TZ - pz) ** 2) ** 0.5
    off = ((DEG * math.atan2(TX - px, -(TZ - pz)) - facing_deg(env) + 180) % 360) - 180
    print(f"  aligned: dist={d0:.2f} off={off:+.1f}")
    for i in range(12):
        px, pz = pos(env)
        da = ((TX - px) ** 2 + (TZ - pz) ** 2) ** 0.5
        step(env, ACT_FORWARD)
        px2, pz2 = pos(env)
        db = ((TX - px2) ** 2 + (TZ - pz2) ** 2) ** 0.5
        offb = ((DEG * math.atan2(TX - px2, -(TZ - pz2)) - facing_deg(env) + 180) % 360) - 180
        print(f"  fwd[{i:2d}] dist {da:6.2f}->{db:6.2f} ({da - db:+.2f})  off={offb:+6.1f}")

    env.close()
    print("\n=== NAV DIAG 2 END ===")


if __name__ == "__main__":
    main()
