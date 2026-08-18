"""READ-ONLY diagnostic: true facing->direction convention + does turn move you?

_diag_nav2 proved facing is QUANTIZED to 45 deg steps (8 headings only), so the
|off|<=4 gate in _navigate_to_coord is unreachable for arbitrary bearings.
Before fixing the primitive we must know the GROUND TRUTH mapping:

  T9. For each of the 8 facings: stop, then 1x forward -> measure (dx,dz).
      That gives the real heading vector per facing, so we can derive the
      correct `want` formula instead of guessing atan2 sign conventions.
  T10. Does turn_right/turn_left move the character (observed drift ~1.6/step)?
      Measured with an explicit stop before each turn.

No memory, no policy, no Sim edits.
"""

import math
import sys

from hierarchical_env import (HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT,
                              ACT_TURN_RIGHT, ACT_NOOP)

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
DEG = 180.0 / math.pi
ACT_STOP = 59


def step(env, a):
    _, _, _, _, info = env.base.step(a)
    env._last_info = info
    return info


def pos(env):
    p = env._last_info.get("player_pos")
    return (p[0], p[1])


def fdeg(env):
    return round((env._last_info.get("facing") or 0.0) * DEG, 1)


def main():
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=SEED)
    env.reset(seed=SEED)
    print(f"=== NAV DIAG 3 seed={SEED} ===")

    # ---- T10: does a turn move the character? (stop before each turn) ----
    print("\n--- T10: turn while explicitly stopped ---")
    step(env, ACT_STOP)
    for i in range(6):
        p0 = pos(env)
        f0 = fdeg(env)
        step(env, ACT_STOP)          # ensure movement flag cleared
        p_stop = pos(env)
        step(env, ACT_TURN_RIGHT)
        p1 = pos(env)
        f1 = fdeg(env)
        d_stop = math.dist(p0, p_stop)
        d_turn = math.dist(p_stop, p1)
        print(f"  [{i}] facing {f0:+7.1f}->{f1:+7.1f}  move_on_stop={d_stop:.3f}  "
              f"move_on_turn={d_turn:.3f}")
    print("  >> move_on_turn ~0  => turn is pure rotation (good).")
    print("  >> move_on_turn >0  => turn also advances; nav must account for it.")

    # ---- T9: ground-truth heading vector per facing ----
    print("\n--- T9: measured heading vector for each of the 8 facings ---")
    print("  facing |    dx     dz   | atan2(dx,-dz) | atan2(dz,dx) | note")
    table = []
    for i in range(9):
        f = fdeg(env)
        step(env, ACT_STOP)
        p0 = pos(env)
        step(env, ACT_FORWARD)
        p1 = pos(env)
        dx, dz = p1[0] - p0[0], p1[1] - p0[1]
        n = math.hypot(dx, dz)
        if n > 1e-6:
            a1 = DEG * math.atan2(dx, -dz)
            a2 = DEG * math.atan2(dz, dx)
            table.append((f, dx, dz, a1, a2))
            print(f"  {f:+7.1f}| {dx:+6.2f} {dz:+6.2f} | {a1:+13.1f} | {a2:+12.1f} | "
                  f"len={n:.2f}")
        else:
            print(f"  {f:+7.1f}| BLOCKED (no movement — wall/terrain)")
        step(env, ACT_STOP)
        step(env, ACT_TURN_LEFT)

    # ---- which formula reproduces facing from the measured vector? ----
    print("\n--- Which formula maps facing -> heading? ---")
    if table:
        err1 = sum(abs(((a1 - f + 180) % 360) - 180) for f, _, _, a1, _ in table) / len(table)
        err2 = sum(abs(((a2 - f + 180) % 360) - 180) for f, _, _, _, a2 in table) / len(table)
        errn1 = sum(abs(((-a1 - f + 180) % 360) - 180) for f, _, _, a1, _ in table) / len(table)
        errn2 = sum(abs(((-a2 - f + 180) % 360) - 180) for f, _, _, _, a2 in table) / len(table)
        print(f"  mean|atan2(dx,-dz) - facing|  = {err1:6.1f} deg   <-- formula in code")
        print(f"  mean|atan2(dz, dx) - facing|  = {err2:6.1f} deg")
        print(f"  mean|-atan2(dx,-dz) - facing| = {errn1:6.1f} deg")
        print(f"  mean|-atan2(dz, dx) - facing| = {errn2:6.1f} deg")
        best = min([(err1, "atan2(dx,-dz)"), (err2, "atan2(dz,dx)"),
                    (errn1, "-atan2(dx,-dz)"), (errn2, "-atan2(dz,dx)")])
        print(f"  >> BEST: {best[1]}  (mean err {best[0]:.1f} deg)")

    # ---- T11: turn_left vs turn_right sign ----
    print("\n--- T11: does turn_left increase or decrease facing? ---")
    step(env, ACT_STOP)
    f0 = fdeg(env)
    step(env, ACT_TURN_LEFT)
    fl = fdeg(env)
    step(env, ACT_TURN_RIGHT)
    fr = fdeg(env)
    print(f"  facing {f0:+.1f} --turn_left--> {fl:+.1f} --turn_right--> {fr:+.1f}")
    dl = ((fl - f0 + 180) % 360) - 180
    print(f"  turn_left delta = {dl:+.1f} deg  => turn_left {'INCREASES' if dl > 0 else 'DECREASES'} facing")

    env.close()
    print("\n=== NAV DIAG 3 END ===")


if __name__ == "__main__":
    main()
