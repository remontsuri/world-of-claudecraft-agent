"""Reproduce farm crash: loop env.step(0), capture last-good state before death."""
from hierarchical_env import HierarchicalWoWEnv
env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
obs, info = env.reset(seed=42)
last = None
for i in range(100):
    try:
        o, r, t, tr, info = env.step(0)
    except RuntimeError as e:
        print(f"CRASH at step {i}")
        if last:
            print("last-good state:")
            print("  pos:", last.get("player_pos"))
            print("  kills:", last.get("kills"))
            print("  targetId:", last.get("targetId"))
            print("  targetDist:", last.get("targetDist"))
            print("  targetOffDeg:", last.get("targetOffDeg"))
            nb = last.get("nearby") or []
            print("  nearby count:", len(nb))
            mobs = [e for e in nb if e.get("kind")=="mob"]
            print("  mob count:", len(mobs))
            if mobs:
                print("  first mob:", {k: mobs[0].get(k) for k in ("id","species","x","z","dist")})
        break
    last = info
    if i % 10 == 0:
        print(f"step {i}: kills={info.get('kills')} pos={info.get('player_pos')} tid={info.get('targetId')}")
else:
    print("100 farm steps OK, kills=", info.get("kills"))
env.close()
