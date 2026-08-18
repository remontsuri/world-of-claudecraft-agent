"""Does raw ACT_TURN_RIGHT crash the server when spammed? Isolate the crash."""
from hierarchical_env import HierarchicalWoWEnv, ACT_TURN_RIGHT
env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=42)
obs, info = env.reset(seed=42)
print("reset ok, pos:", info.get("player_pos"))
for i in range(50):
    try:
        _, _, _, _, info = env.base.step(ACT_TURN_RIGHT)
    except RuntimeError as e:
        print(f"CRASH at turn iter {i}: {e}")
        break
else:
    print(f"50 turns ok, final facing={info.get('facing')}")
env.close()
