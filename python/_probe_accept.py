"""Debug accept_quest: what does the server return?"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT, ACT_TURN_RIGHT

env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=42)
obs, info = env.reset(seed=42)
# find giver
giver = None
for _ in range(24):
    env.base.step(ACT_FORWARD)
    env.base.step(ACT_TURN_LEFT)
    near = env._last_info.get("nearby") or []
    g = [e for e in near if (e.get("kind")=="npc") and (e.get("questIds") or e.get("questId"))]
    if g:
        giver = g[0]; break
print("giver:", giver.get("id"), giver.get("questIds"))
env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
print("arrived, pos:", env._last_info.get("player_pos"), "giver at", (giver.get("x"), giver.get("z")))
# try accept
qid = (giver.get("questIds") or [None])[0]
out = env.base.accept_quest(str(qid))
print("accept_quest out keys:", list(out.keys()))
print("info quests:", out.get("quests"))
print("active:", (out.get("quests") or {}).get("active"))
env.close()
