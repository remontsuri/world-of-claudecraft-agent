"""READ-ONLY timing: where does experiment_b3_control hang on seed 4242?

We know from _diag_farmtiming that farm-drift to far+mob takes ~51s. But
experiment_b3_control printed nothing for 385s on the first force_far_mob. This
probe times each stage: accept_welcome, then force_far_mob, and logs per-10-iter
of force. If force_far_mob never terminates (player moves but never hits
far+mob), we'll see it stall here too and can fix the termination.
"""

import time

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from world_state import build_world_state
from memory import _bucket

SEED = 4242


def accept_welcome(env):
    t = time.time()
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
    print(f"  accept_welcome: {time.time()-t:.1f}s")
    return True


def has_mob(info):
    near = info.get("nearby") or []
    return any((e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")
               for e in near)


def is_far(info):
    return "far=1" in _bucket(build_world_state(info))


def is_real(info):
    ws = build_world_state(info)
    return ws["quest_status"] == "ACTIVE" and "far=1" in _bucket(ws) and has_mob(info)


env = HierarchicalWoWEnv(player_class="warrior", max_steps=8000, seed=SEED)
env.reset(seed=SEED)
accept_welcome(env)

t0 = time.time()
stuck = 0
prev = None
for i in range(150):
    if is_real(env._last_info):
        print(f"  FAR+MOB at iter {i}, t={time.time()-t0:.1f}s")
        break
    if i % 10 == 0:
        ws = build_world_state(env._last_info)
        print(f"  force iter{i:3d} t={time.time()-t0:5.1f}s dist={ws['distance_to_giver']:.1f} "
              f"mob={has_mob(env._last_info)} far={is_far(env._last_info)}")
    try:
        env.step(0)
    except Exception as ex:
        print(f"  crash {ex!r}")
        break
    pos = env._last_info.get("player_pos")
    if prev and abs(pos[0]-prev[0]) < 0.1 and abs(pos[1]-prev[1]) < 0.1:
        stuck += 1
        if stuck >= 5:
            env.base.step(ACT_FORWARD); env.base.step(ACT_TURN_LEFT); stuck = 0
    else:
        stuck = 0
    prev = pos
else:
    print(f"  NOT reached in 150 iters, t={time.time()-t0:.1f}s")
env.close()
print("done")
