"""Fast C2 probe: 1 kill + 1 loot, then inspect inventory + sell_junk.
No inner farm loops — just enough to see what lootCorpse actually drops and
whether sell_junk changes copper. Timeout-guarded by caller."""
from hierarchical_env import HierarchicalWoWEnv

env = HierarchicalWoWEnv(player_class="warrior", max_steps=400, seed=42)
obs, info = env.reset(seed=42)
k0 = info.get("kills", 0)
# single farm skill call (SKILL_STEPS=120 low-level steps)
for _ in range(3):
    o, r, t, tr, i = env.step(0)
    if i.get("kills", 0) > k0:
        info = i; break

print(f"after farm: kills={info.get('kills')} copper={info.get('copper')}")
# loot via skill (step 1 = loot)
_, _, _, _, info = env.step(1)
inv = info.get("inventory") or []
print(f"after loot: inv_items={len(inv)} copper={info.get('copper')}")
from collections import Counter
qc = Counter()
for it in inv:
    qc[(it.get('itemId'), it.get('quality'))] += it.get('count', 1)
for (iid, q), c in qc.items():
    print(f"  {iid} quality={q} x{c}")

c0 = info.get("copper", 0)
sold = env.base.sell_junk()
c1 = sold.get("copper", 0)
print(f"sell_junk: copper {c0}->{c1} delta={c1-c0}")
env.close()
