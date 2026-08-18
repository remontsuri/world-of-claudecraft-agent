"""Debug farm-with-species-filter: does it ever attack forest_wolf?"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
obs, info = env.reset(seed=42)
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
env._skill_target_species = "forest_wolf"
for i in range(8):
    env.step(0)
    li = env._last_info
    tid = li.get("targetId")
    mob = next((e for e in (li.get("nearby") or []) if e.get("id")==tid), None)
    sp = mob.get("species") if mob else "?"
    fw_near = sum(1 for e in (li.get("nearby") or []) if e.get("species")=="forest_wolf")
    print(f"step {i}: kills={li.get('kills')} targetId={tid} targetSpecies={sp} forest_wolf_in_nearby={fw_near}")
env._skill_target_species = None
env.close()
