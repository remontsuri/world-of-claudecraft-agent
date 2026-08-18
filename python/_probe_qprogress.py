"""Does farm-with-species-filter actually move q_wolves progress?"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
obs, info = env.reset(seed=42)
# accept q_wolves
giver = None
for _ in range(24):
    env.base.step(ACT_FORWARD); env.base.step(ACT_TURN_LEFT)
    near = env._last_info.get("nearby") or []
    g = [e for e in near if e.get("kind")=="npc" and (e.get("questIds") or e.get("questId"))]
    if g:
        giver = g[0]; break
qid = (giver.get("questIds") or [None])[0]
env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
env.base.accept_quest(str(qid)); env._last_info = env.base.accept_quest(str(qid))
# farm with species filter
env._skill_target_species = "forest_wolf"
for i in range(15):
    env.step(0)
    if i % 3 == 0:
        aq = [q for q in (env._last_info.get("quests",{}).get("active") or []) if q.get("id")==qid]
        cur = aq[0]["objectives"][0]["current"] if aq else "?"
        print(f"farm {i}: kills={env._last_info.get('kills')} qprogress={cur}")
env._skill_target_species = None
env.close()
