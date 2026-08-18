"""Probe: after killing a mob, does interact(22) loot the corpse in headless?"""
from wow_env import WoWClassicEnv

env = WoWClassicEnv(player_class="warrior", max_steps=5000)
obs, info = env.reset(seed=42)
inv0 = len([1 for s in info.get("inventory_snapshot", [])]) if "inventory_snapshot" in info else 0
# farm one mob using same nav as hierarchical_env
copper0 = info.get("copper", 0)
for i in range(200):
    env.step(8)  # target_nearest
    off = info.get("targetOffDeg")
    if off is not None and abs(off) > 4:
        env.step(4 if off > 0 else 3)
        continue
    obs, r, term, trunc, info = env.step(1)  # forward
    if info.get("targetId") is not None and abs(info.get("targetOffDeg") or 999) < 10:
        obs, r, term, trunc, info = env.step(9)  # attack
    if info.get("kills", 0) > 0:
        print(f"killed at step {i}, copper={info.get('copper')}")
        break

# now loot: interact repeatedly near corpse
for j in range(10):
    obs, r, term, trunc, info = env.step(22)
    if term or trunc:
        break
print(f"after interact: copper {copper0} -> {info.get('copper')}, kills={info.get('kills')}")
env.close()
