"""READ-ONLY: why does return_to_giver get reward=-0.5486 when it closes distance?

Trace shows return closes 81.7->3.7 (dist_progress should be +1.56 at 0.02/unit)
yet outcome_reward returned -0.5486. Suspect: verdict=FAILURE, or died=True
(death on the way back), or ws_before/ws_after distance mismatch in the
measurement path. This probe runs one return from far and prints the exact
inputs to outcome_reward.
"""

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability
from quest_skill import return_to_giver
from world_state import build_world_state
from reward import outcome_reward

SEED = 4242

env = HierarchicalWoWEnv(player_class="warrior", max_steps=4000, seed=SEED)
env.reset(seed=SEED)
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
for _ in range(60):
    env._last_info = env.base.step(ACT_FORWARD)[4]
    if build_world_state(env._last_info)["distance_to_giver"] > 80:
        break

ws_before = build_world_state(env._last_info)
print(f"before: dist={ws_before['distance_to_giver']:.1f} deaths={ws_before['deaths']}")
res = return_to_giver(env, {})
ws_after = build_world_state(env._last_info)
print(f"after:  dist={ws_after['distance_to_giver']:.1f} deaths={ws_after['deaths']} verdict={res}")
rew = outcome_reward(ws_before, ws_after, res, "OK")
print(f"reward={rew:.4f}")
print(f"  dist_progress part = {(ws_before['distance_to_giver'] - ws_after['distance_to_giver']) * 0.02:.4f}")
print(f"  died = {ws_after['deaths'] > ws_before['deaths']}")
env.close()
