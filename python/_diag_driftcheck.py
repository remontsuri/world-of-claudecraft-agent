"""READ-ONLY quick check: does direct farm drift (env.step(0)) actually reach
far=1 on the EVAL seeds used by experiment_b2.py (4242, 5353, 6464)?

The previous experiment found 0 far-decisions because forcing went through the
policy. This probe confirms the fixed harness (plain farm) reaches far on those
exact seeds, so the real run won't come back empty.
"""

import sys
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from world_state import build_world_state
from memory import _bucket

SEEDS = [4242, 5353, 6464]


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


for seed in SEEDS:
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=seed)
    env.reset(seed=seed)
    ok = accept_welcome(env)
    reached = False
    dist0 = build_world_state(env._last_info)["distance_to_giver"]
    for i in range(60):
        info = env._last_info
        if "far=1" in _bucket(build_world_state(info)):
            reached = True
            di = build_world_state(info)["distance_to_giver"]
            print(f"  seed={seed}: reached far at farm#{i} dist={di:.1f}")
            break
        try:
            env.step(0)
        except Exception as ex:
            print(f"  seed={seed}: crashed at farm#{i}: {ex!r}")
            break
    if not reached:
        di = build_world_state(env._last_info)["distance_to_giver"]
        print(f"  seed={seed}: NOT far after 60 farm bursts (dist={di:.1f}, start={dist0:.1f})")
    env.close()

print("done")
