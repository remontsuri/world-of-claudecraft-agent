"""What species are actually visible near spawn during farm?"""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from collections import Counter
env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
obs, info = env.reset(seed=42)
c = Counter()
for _ in range(20):
    env.step(0)
    for e in (env._last_info.get("nearby") or []):
        if e.get("kind")=="mob": c[e.get("species")] += 1
    if env._last_info.get("kills",0) >= 5: break
print("species seen while farming:", dict(c))
print("kills:", env._last_info.get("kills"))
env.close()
