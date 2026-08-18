"""Does many farm skills (env.step(0)) in a row crash the server?"""
from hierarchical_env import HierarchicalWoWEnv
env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
obs, info = env.reset(seed=42)
print("reset ok")
for i in range(30):
    try:
        o, r, t, tr, info = env.step(0)
        k = info.get("kills", 0)
        if i % 5 == 0:
            print(f"farm {i}: kills={k} pos={info.get('player_pos')}")
    except RuntimeError as e:
        print(f"CRASH at farm iter {i}: {e}")
        break
else:
    print(f"30 farm skills ok, kills={info.get('kills')}")
env.close()
