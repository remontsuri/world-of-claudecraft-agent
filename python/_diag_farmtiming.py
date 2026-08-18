"""READ-ONLY timing: how long does farm-drift to far+mob actually take on seed
4242, and where does it stall? Logs per-10-iter time + dist + mob.

The B3 run stalled >130s on the first force_far_mob (seed 4242). We need the real
number before changing the forcing strategy. If farm-drift is just inherently
slow (each env.step(0) is a full attack+loot+nav cycle on a shared CPU server),
the fix is a HYBRID force: plain forward (fast, ~26 steps to far) then short farm
bursts for mob_nearby. If it stalls (player moves but never hits far+mob), the
fix is a different termination.
"""

import time

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from world_state import build_world_state
from memory import _bucket


def accept_welcome(env):
    cap = QuestCapability(env)
    if cap.find_active_quest() is not None:
        return True
    giver = None
    for _ in range(24):
        env.base.step(ACT_FORWARD)
        env.base.step(ACT_TURN_LEFT)
        near = env._last_info.get("nearby") or []
        g = [e for e in near
             if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
        if g:
            giver = g[0]
            break
    if not giver:
        return False
    qid = (giver.get("questIds") or [None])[0]
    env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
    env._last_info = env.base.accept_quest(str(qid))
    return True


def has_mob(info):
    near = info.get("nearby") or []
    return any((e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")
               for e in near)


env = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=4242)
env.reset(seed=4242)
accept_welcome(env)
t0 = time.time()
stuck = 0
prev = None
for i in range(150):
    ws = build_world_state(env._last_info)
    if "far=1" in _bucket(ws) and has_mob(env._last_info):
        print(f"  >> FAR+MOB at iter {i}, t={time.time()-t0:.1f}s, dist={ws['distance_to_giver']:.1f}")
        break
    ts = time.time()
    env.step(0)
    dt = time.time() - ts
    if i % 10 == 0:
        print(f"  iter{i:3d} t={time.time()-t0:5.1f}s dt/step={dt:.2f}s dist={ws['distance_to_giver']:.1f} "
              f"mob={has_mob(env._last_info)} prog={ws['quest_progress']}")
    pos = env._last_info.get("player_pos")
    if prev and abs(pos[0]-prev[0]) < 0.1 and abs(pos[1]-prev[1]) < 0.1:
        stuck += 1
        if stuck >= 5:
            env.base.step(ACT_FORWARD); env.base.step(ACT_TURN_LEFT); stuck = 0
    else:
        stuck = 0
    prev = pos
else:
    print(f"  not reached in 150 iters, t={time.time()-t0:.1f}s")
env.close()
print("done")
