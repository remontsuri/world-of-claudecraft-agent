"""Inspect real quest state structure from headless server.
We already proved accept_quest works (q_wolves in active). Now dump the FULL
shape of an active quest so the GoalManager can read objectives/progress
without guessing. No navigation, just accept + inspect.
"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT

env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=42)
obs, info = env.reset(seed=42)
# find + accept a quest
giver = None
for _ in range(24):
    env.base.step(ACT_FORWARD); env.base.step(ACT_TURN_LEFT)
    near = env._last_info.get("nearby") or []
    g = [e for e in near if e.get("kind")=="npc" and (e.get("questIds") or e.get("questId"))]
    if g:
        giver = g[0]; break
qid = (giver.get("questIds") or [None])[0]
env.base.accept_quest(str(qid))
env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
out = env.base.accept_quest(str(qid))  # idempotent re-accept to refresh
print("=== quests block ===")
import json
print(json.dumps(out.get("quests"), indent=2, default=str)[:3000])
print("=== npcs block (quest-related fields) ===")
npcs = out.get("npcs") or {}
print("npcs keys:", list(npcs.keys()))
for k, v in npcs.items():
    print(f"  {k}: type={type(v).__name__} len={len(v) if hasattr(v,'__len__') else '?'}")
    if isinstance(v, list) and v:
        print(f"    [0] keys: {list(v[0].keys()) if isinstance(v[0], dict) else v[0]}")
    if isinstance(v, dict) and v:
        sample = list(v.items())[0]
        print(f"    sample key={sample[0]} valtype={type(sample[1]).__name__}")
        if isinstance(sample[1], dict):
            print(f"      val keys: {list(sample[1].keys())[:15]}")
        elif isinstance(sample[1], list) and sample[1]:
            print(f"      val[0] type={type(sample[1][0]).__name__} keys={list(sample[1][0].keys()) if isinstance(sample[1][0], dict) else sample[1][0]}")
env.close()
