"""Smoke-test action_masks(): after reset + a farm kill, masks reflect world.
Proves Phase D basis is ready without a long PPO run. Uses stub base for speed."""
from hierarchical_env import HierarchicalWoWEnv, N_SKILLS
import numpy as np

class _Stub:
    def step(self, a): return (None, 0.0, False, False, {})
    def reset(self, seed=None): return (None, {})
    def loot_corpse(self, c): return {"nearby": [], "kills": 0, "copper": 0, "quests_done": 0, "looted": True}
    def turn_in_quest(self, q): return {}
    def harvest_node(self, n, a): return {}
    def sell_junk(self): return {"nearby": [], "kills": 0, "copper": 0, "quests_done": 0}

env = HierarchicalWoWEnv()
env.base = _Stub()

# empty world: only heal masked (unconditional)
env._last_info = {"nearby": []}
m0 = env.action_masks()
print("empty world mask:", m0.tolist())
assert bool(m0[7]) is True and bool(m0[6]) is False and bool(m0[8]) is False and bool(m0[9]) is False, "heal on, craft/equip/buy off"
assert not bool(m0[0]) and not bool(m0[1]), "no mob/corpse -> farm/loot off"

# world with mob + corpse
env._last_info = {"nearby": [
    {"id": 1, "type": "mob", "dist": 5},
    {"id": 787, "type": "corpse", "looted": False, "dist": 3},
], "targetId": None}
m1 = env.action_masks()
print("mob+corpse mask:", m1.tolist())
assert m1[0] and m1[1], "mob->farm on, corpse->loot on"
assert not m1[2] and not m1[5], "no quest npc / node -> off"

# world with quest npc (questIds non-empty)
env._last_info = {"nearby": [{"id": 5, "kind": "npc", "questIds": ["q1"], "dist": 4}]}
m2 = env.action_masks()
print("quest npc mask:", m2.tolist())
assert m2[2], "quest npc -> accept_quest on"

# world with ready quest
env._last_info = {"nearby": [], "quests": {"active": [{"id": "q1", "state": "ready"}]}}
m3 = env.action_masks()
assert m3[3], "ready quest -> turn_in_quest on"

print("MASKS OK: farm/loot/quest/gather masked by world; craft/equip/buy always off; heal always on")
