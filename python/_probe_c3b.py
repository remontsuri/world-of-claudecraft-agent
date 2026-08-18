"""C3b: are harvest nodes anywhere in the world (just out of observe range)?
Dump materials list + scan entities for kind/type node near start."""
from wow_env import WoWClassicEnv

env = WoWClassicEnv(player_class="warrior", max_steps=500)
obs, info = env.reset(seed=42)
g = info.get("gather") or {}
print("materials:", g.get("materials"))
print("all info keys:", sorted(info.keys()))
# entities aren't in info normally; check nearby for any 'node' kind
near = info.get("nearby") or []
kinds = {}
for e in near:
    k = e.get("kind") or e.get("type") or "?"
    kinds[k] = kinds.get(k, 0) + 1
print("nearby kinds:", kinds, "count=", len(near))
# try a far walk to surface nodes? Not now — just confirm none at spawn.
env.close()
