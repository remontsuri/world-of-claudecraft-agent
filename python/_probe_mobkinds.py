"""What mob kinds exist near spawn after farming? Need forest_wolf for q_wolves."""
from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from collections import Counter
env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
obs, info = env.reset(seed=42)
kinds = Counter()
for _ in range(30):
    o,r,t,tr,i = env.step(0)
    for e in (i.get("nearby") or []):
        if e.get("kind")=="mob" or e.get("type")=="mob":
            kinds[e.get("type") or e.get("kind")] += 1
    if i.get("kills",0) >= 8:
        break
print("mob types seen:", dict(kinds))
print("final kills:", i.get("kills"))
# also: quests progress
print("quests active:", [(q.get("id"), q.get("objectives")) for q in i.get("quests",{}).get("active",[])])
env.close()
