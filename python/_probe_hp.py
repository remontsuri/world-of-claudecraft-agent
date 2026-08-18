"""Probe: does farming actually reduce HP? (warrior vs forest_wolf)"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability

env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=42)
obs, info = env.reset(seed=42)
# accept welcome so there is a target context
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

for i in range(100):
    env.step(0)
    p = env._last_info.get("player", {}) or {}
    hp = p.get("hp"); maxhp = p.get("maxHp") or p.get("hpMax") or 1
    hf = (hp/maxhp) if hp is not None else 1.0
    if i % 10 == 0:
        print(f"farm {i}: hp_frac={hf:.3f} hp={hp} maxhp={maxhp} deaths={env._last_info.get('deaths')} kills={env._last_info.get('kills')}")
env.close()
