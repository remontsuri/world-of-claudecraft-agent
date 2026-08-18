"""READ-ONLY A/B of nav variants against the SIM'S OWN documented convention.

Ground truth from the game source (NOT guessed):
  src/sim/player_motion.ts:286  "facing f points along (sin f, cos f)"
        -> bearing to a point is atan2(dx, dz)   [code uses atan2(dx, -dz) = BUG]
  src/sim/player_motion.ts:288  "Turning right therefore DECREASES facing"
        -> to raise facing (off>0) you must turn LEFT
           [code does TURN_RIGHT if off > 0     = BUG]
  src/sim/obs.ts:80-87          turn_left/right ALSO set inp.forward = true
        -> a turn always advances; you cannot pivot in place
  measured: facing is quantized to 45 deg (8 headings)
        -> the |off|<=4 gate is unreachable; needs >= 22.5 (half-quantum)

Variants, identical start state and step budget:
  V0 current : atan2(dx,-dz), TURN_RIGHT if off>0, gate 4      (as shipped)
  V1 fix Z   : atan2(dx, dz), TURN_RIGHT if off>0, gate 4
  V2 fix both: atan2(dx, dz), TURN_LEFT  if off>0, gate 4
  V3 fix+gate: atan2(dx, dz), TURN_LEFT  if off>0, gate 22.5
No edits to hierarchical_env.py yet — this decides the fix empirically first.
"""

import math
import sys

from hierarchical_env import (HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT,
                              ACT_TURN_RIGHT, ACT_STRAFE_RIGHT)

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
DEG = 180.0 / math.pi
TX, TZ = 4.5, 5.5


def step(env, a):
    _, _, _, _, info = env.base.step(a)
    env._last_info = info


def pos(env):
    p = env._last_info.get("player_pos")
    return (p[0], p[1])


def dist_to(env, tx=TX, tz=TZ):
    px, pz = pos(env)
    return math.hypot(tx - px, tz - pz)


def nav(env, tx, tz, max_steps, flip_z, turn_right_on_pos, gate):
    best = None
    no_progress = 0
    last_pos = None
    stuck = 0
    for i in range(max_steps):
        px, pz = pos(env)
        dx, dz = tx - px, tz - pz
        d = math.hypot(dx, dz)
        if d < 5:
            return True, i, d
        if best is None or d < best - 0.5:
            best, no_progress = d, 0
        else:
            no_progress += 1
            if no_progress >= 30:
                return False, i, d
        want = DEG * (math.atan2(dx, -dz) if flip_z else math.atan2(dx, dz))
        facing = (env._last_info.get("facing") or 0.0) * DEG
        off = ((want - facing + 180.0) % 360.0) - 180.0
        if abs(off) > gate:
            if turn_right_on_pos:
                step(env, ACT_TURN_RIGHT if off > 0 else ACT_TURN_LEFT)
            else:
                step(env, ACT_TURN_LEFT if off > 0 else ACT_TURN_RIGHT)
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
    return False, max_steps, dist_to(env, tx, tz)


def drift_away(env, want_dist, max_steps=500):
    """Harness drift: plain forward until far. Not a policy decision."""
    for _ in range(max_steps):
        if dist_to(env) >= want_dist:
            return True
        step(env, ACT_FORWARD)
    return False


def run(name, flip_z, trop, gate, seed, start_dist):
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=seed)
    env.reset(seed=seed)
    drift_away(env, start_dist)
    d0 = dist_to(env)
    ok, steps, d1 = nav(env, TX, TZ, 300, flip_z, trop, gate)
    env.close()
    print(f"  {name:38s} {d0:7.1f} -> {d1:7.1f}  closed={d0 - d1:+8.1f}  "
          f"arrived={str(ok):5s} steps={steps}")
    return d0 - d1, ok


def main():
    print(f"=== NAV A/B (source-derived fix) seed={SEED} ===")
    for start in (60.0, 120.0):
        print(f"\n--- start distance ~{start:.0f}u ---")
        r = {}
        r["V0"] = run("V0 current  atan2(dx,-dz) R+ g=4  ", True, True, 4.0, SEED, start)
        r["V1"] = run("V1 fixZ     atan2(dx, dz) R+ g=4  ", False, True, 4.0, SEED, start)
        r["V2"] = run("V2 fixZ+dir atan2(dx, dz) L+ g=4  ", False, False, 4.0, SEED, start)
        r["V3"] = run("V3 fixZ+dir+gate         L+ g=22.5", False, False, 22.5, SEED, start)
        best = max(r.items(), key=lambda kv: kv[1][0])
        print(f"  >> BEST: {best[0]} (closed {best[1][0]:+.1f}, arrived={best[1][1]})")
    print("\n=== END ===")


if __name__ == "__main__":
    main()
