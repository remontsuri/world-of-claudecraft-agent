"""READ-ONLY: does return_to_giver (budget=80, DIRECT nav to giver, no waypoints)
actually decrease distance_to_giver now?

Previous version followed server navPath waypoints -> return INCREASED distance
(M3 +61). This probe calls return_to_giver 10x from a far state and logs
dist_before -> dist_after per call. If it now closes distance, the full B3-control
re-run is worth the 30 min.
"""

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from quest_skill import return_to_giver
from world_state import build_world_state

SEED = 4242

cap = QuestCapability
env = HierarchicalWoWEnv(player_class="warrior", max_steps=4000, seed=SEED)
env.reset(seed=SEED)
# accept welcome
c = QuestCapability(env)
if c.find_active_quest() is None:
    for _ in range(24):
        env.base.step(ACT_FORWARD); env.base.step(ACT_TURN_LEFT)
        near = env._last_info.get("nearby") or []
        g = [e for e in near if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
        if g:
            qid = (g[0].get("questIds") or [None])[0]
            env._navigate_to_coord(g[0]["x"], g[0]["z"], max_steps=80)
            env._last_info = env.base.accept_quest(str(qid))
            break
# walk away to far
for _ in range(60):
    env._last_info = env.base.step(ACT_FORWARD)[4]
    if build_world_state(env._last_info)["distance_to_giver"] > 80:
        break

print(f"start dist={build_world_state(env._last_info)['distance_to_giver']:.1f}")
for i in range(10):
    d0 = build_world_state(env._last_info)["distance_to_giver"]
    res = return_to_giver(env, {})
    d1 = build_world_state(env._last_info)["distance_to_giver"]
    print(f"  call {i}: {d0:.1f} -> {d1:.1f}  ({d1-d0:+.1f})  res={res}")
env.close()
print("done")
