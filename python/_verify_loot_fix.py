import importlib.util

spec = importlib.util.spec_from_file_location("he", r"D:/world-of-claudecraft/python/hierarchical_env.py")
he = importlib.util.module_from_spec(spec)
spec.loader.exec_module(he)
print("SKILLS =", he.SKILLS)
print("N_SKILLS =", he.N_SKILLS)
print("ACT_INTERACT =", he.ACT_INTERACT)
print("loot index =", he.SKILLS.index("loot"))

# regression asserts: dict index MUST dispatch to the intended skill,
# not silently fall through to a noop (the exact class of bug found here).
assert he.SKILLS[1] == "loot", f"SKILLS[1] must be 'loot', got {he.SKILLS[1]}"
assert he.ACT_INTERACT == 58, f"ACT_INTERACT must be 58, got {he.ACT_INTERACT}"


class FakeBase:
    def __init__(self):
        self.calls = []

    def step(self, a):
        return None, 0.0, False, False, {"nearby": [], "inventory": []}

    def loot_corpse(self, cid):
        self.calls.append(cid)
        return {"nearby": [], "inventory": [{"itemId": 1}], "kills": 0, "copper": 0, "quests_done": 0}


class FakeEnv(he.HierarchicalWoWEnv):
    def __init__(self):
        self.base = FakeBase()
        self._last_info = {"nearby": [], "kills": 0, "copper": 0, "quests_done": 0}
        self._high_step = 0


env = FakeEnv()
env._last_info = {
    "nearby": [
        {"id": 787, "kind": "mob", "lootable": True, "looted": False, "dist": 3},
        {"id": 999, "kind": "mob", "lootable": True, "looted": True, "dist": 1},
    ],
    "kills": 0, "copper": 0, "quests_done": 0,
}

r, done = env._run_skill(1)  # step(1) теперь = loot
print("loot_corpse called with cid =", env.base.calls, "(expected [787])")
print("reward delta =", r)

# отрицательный тест: все трупы looted -> noop, команда НЕ шлётся
env2 = FakeEnv()
env2._last_info = {"nearby": [
    {"id": 1, "kind": "mob", "lootable": True, "looted": True}], "kills": 0, "copper": 0, "quests_done": 0}
r2, _ = env2._run_skill(1)
print("all-looted -> loot_corpse calls =", env2.base.calls, "(expected [])")
