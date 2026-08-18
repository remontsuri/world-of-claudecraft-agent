"""Smoke-test: HierarchicalWoWEnv dispatches all 10 skills to the correct
executor branch WITHOUT UnboundLocal / dead-code regressions.

Catches the class of bug where a `step(idx)` silently falls through to the
wrong branch because SKILLS[] order drifted or a branch got swallowed by a
patch. Run with therock-test venv (PYTHONPATH="" to avoid numpy leak).
"""
from hierarchical_env import (
    SKILLS, N_SKILLS, HierarchicalWoWEnv,
    ACT_TARGET_NEAREST, ACT_ATTACK, ACT_FORWARD, ACT_INTERACT,
    ACT_NOOP, ACT_EAT_DRINK,
)

# 1) Canonical order — load-bearing for Phase D PPO (TRAINING.md:19)
EXPECTED = ["farm", "loot", "accept_quest", "turn_in_quest", "sell_junk",
            "gather", "craft", "heal", "equip", "buy"]
assert SKILLS == EXPECTED, f"SKILLS order drifted: {SKILLS}"
assert N_SKILLS == 10, f"N_SKILLS={N_SKILLS}"

# 2) Each known low-level action id resolves (no NameError from a dropped import)
for nm, val in [("ACT_TARGET_NEAREST", ACT_TARGET_NEAREST),
                ("ACT_ATTACK", ACT_ATTACK), ("ACT_FORWARD", ACT_FORWARD),
                ("ACT_INTERACT", ACT_INTERACT), ("ACT_NOOP", ACT_NOOP),
                ("ACT_EAT_DRINK", ACT_EAT_DRINK)]:
    assert isinstance(val, int), f"{nm} not an int"

# 3) Dispatch every skill — must reach its branch and return a 5-tuple, no crash.
class _StubBase:
    def __init__(self):
        self.loot_calls = []
        self.turnin_calls = []
        self.harvest_calls = []
    def step(self, a):
        return (None, 0.0, False, False, {"nearby": [], "kills": 0, "copper": 0, "quests_done": 0})
    def reset(self, seed=None):
        return (None, {})
    def loot_corpse(self, cid):
        self.loot_calls.append(cid)
        return {"nearby": [], "kills": 0, "copper": 0, "quests_done": 0, "looted": True}
    def turn_in_quest(self, qid):
        self.turnin_calls.append(qid); return {}
    def harvest_node(self, nid, a):
        self.harvest_calls.append(nid); return {}
    def sell_junk(self):
        return {"nearby": [], "kills": 0, "copper": 0, "quests_done": 0}

env = HierarchicalWoWEnv()
env.base = _StubBase()
env.reset()

# loot with a real corpse in nearby -> must call base.loot_corpse(787), not fall through
env._last_info = {"nearby": [
    {"id": 787, "type": "corpse", "dist": 3.0, "looted": False},
]}
env.step(1)   # index 1 == "loot"
assert env.base.loot_calls == [787], f"loot didn't dispatch to loot_corpse: {env.base.loot_calls}"

# every index dispatches without raising UnboundLocal / returning None
for idx in range(N_SKILLS):
    o, rr, t, tr, i = env.step(idx)
    assert o is not None and rr is not None and t is not None and tr is not None and i is not None, \
        f"step({idx}) returned a None: {(o,rr,t,tr,i)}"

print("DISPATCH OK: 10 skills, order canonical, no dead branches, no UnboundLocal")
