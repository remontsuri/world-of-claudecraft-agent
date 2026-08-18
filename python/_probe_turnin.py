"""Debug turn_in: after 8 kills, what is q_wolves state + is turnInNpc nearby?"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
obs, info = env.reset(seed=42)
# accept
giver = None
for _ in range(24):
    env.base.step(ACT_FORWARD); env.base.step(ACT_TURN_LEFT)
    near = env._last_info.get("nearby") or []
    g = [e for e in near if e.get("kind")=="npc" and (e.get("questIds") or e.get("questId"))]
    if g:
        giver = g[0]; break
qid = (giver.get("questIds") or [None])[0]
env.base.accept_quest(str(qid)); env._last_info = env.base.accept_quest(str(qid))
# farm until 8 kills
for _ in range(30):
    o,r,t,tr,i = env.step(0)
    if i.get("kills",0) >= 8:
        info = i; break
# inspect quest + npcs
qs = info.get("quests",{}).get("active",[])
print("quest:", qs)
near = info.get("nearby") or []
npc_ids = [e.get("id") for e in near if e.get("kind")=="npc"]
print("nearby npc ids:", npc_ids[:20])
print("marshal_redbrook in nearby?", "marshal_redbrook" in npc_ids)
# try turn_in raw
out = env.base.turn_in_quest("q_wolves")
print("turn_in out quests:", out.get("quests"))
print("turn_in done:", (out.get("quests") or {}).get("done"))
env.close()
