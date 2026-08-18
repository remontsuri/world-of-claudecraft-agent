"""Probe: what does info['quests'] actually contain after accepting welcome?"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from policy import GoalManager
from memory import ExperienceStore

env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=42)
obs, info = env.reset(seed=42)
cap = QuestCapability(env)
giver = None
for _ in range(24):
    env.base.step(ACT_FORWARD); env.base.step(ACT_TURN_LEFT)
    near = env._last_info.get("nearby") or []
    g = [e for e in near if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
    if g:
        giver = g[0]; break
if giver:
    qid = (giver.get("questIds") or [None])[0]
    env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
    env.base.accept_quest(str(qid))
    env._last_info = env.base.accept_quest(str(qid))

print("=== info['quests'] keys:", list(env._last_info.get("quests", {}).keys()))
print("=== active:", env._last_info.get("quests", {}).get("active"))
print("=== done:", env._last_info.get("quests", {}).get("done"))
print("=== available:", env._last_info.get("quests", {}).get("available"))

gm = GoalManager(ExperienceStore(), seed=1)
ws = gm._world_state(env._last_info)
print("=== policy._world_state:", ws)
print("=== policy._candidates:", gm._candidates(env._last_info, ws))
env.close()
