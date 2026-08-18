"""Debug _navigate_to_coord: can we reach a close coord (4.5,5.5)?"""
import math
from hierarchical_env import HierarchicalWoWEnv

env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=42)
obs, info = env.reset(seed=42)
print("spawn pos:", info.get("player_pos"), "facing:", info.get("facing"))
ok = env._navigate_to_coord(4.5, 5.5, max_steps=80)
print("arrived:", ok)
print("final pos:", env._last_info.get("player_pos"))
px, pz = env._last_info.get("player_pos", [0,0])
d = ((4.5-px)**2 + (5.5-pz)**2)**0.5
print("final dist:", d)
env.close()
