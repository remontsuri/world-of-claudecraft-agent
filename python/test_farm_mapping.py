"""
RED -> GREEN: farm skill must call the bridge FARM action (idx=0), NOT
ACT_TARGET_NEAREST (idx=8 = equip) / ACT_ATTACK (idx=9 = buy).

Root cause (2026-08-30, live-proven):
- hierarchical_env.ACT_TARGET_NEAREST = 8, ACT_ATTACK = 9
- but bridge actions.cjs case 8 = EQUIP, case 9 = BUY
- bridge case 0 = FARM (chase + targetEntity + startAutoAttack until death)
- So farm sent equip/buy instead of attacking -> kills=0, farm reported success
  (bridge ok:true from equip/buy), agent never killed a mob.

Test drives the REAL _run_skill farm branch via step(0) with a FakeBase.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hierarchical_env as he


class FakeBase:
    def __init__(self):
        self.calls = []
        self._last_info = {"targetId": None, "kills": 0, "quests": {"active": []}}

    def step(self, idx, ctx=None):
        self.calls.append(idx)
        if idx == he.ACT_FARM:
            self._last_info = {"targetId": 88, "kills": 1, "quests": {"active": []}}
        return None, 0.0, False, False, self._last_info


def test_farm_calls_bridge_farm_not_equip_buy():
    base = FakeBase()
    env = he.HierarchicalWoWEnv.__new__(he.HierarchicalWoWEnv)
    env.base = base
    env._last_info = {"nearby": [{"id": 88, "kind": "mob", "x": 0, "z": 0, "dist": 5,
                                   "hostile": True, "dead": False}],
                      "player_pos": [0, 0], "targetId": None, "kills": 0,
                      "quests": {"active": []}}
    env._high_step = 0
    env.max_high_steps = 1000
    # SKILLS[0] == "farm"  ->  step(0) runs the farm branch
    env.step(0)
    # FAIL (before fix): sends [8] (equip) — never attacks
    # PASS (fixed):      sends only [he.ACT_FARM, ...] (idx 0 = bridge FARM combo)
    assert all(c == he.ACT_FARM for c in base.calls), (
        f"farm sent {base.calls}, expected only [{he.ACT_FARM}] "
        f"(bridge case 0 = FARM, not {he.ACT_TARGET_NEAREST}=equip / {he.ACT_ATTACK}=buy)"
    )
    assert he.ACT_TARGET_NEAREST not in base.calls, "farm must NOT send equip (idx 8)"
    assert he.ACT_ATTACK not in base.calls, "farm must NOT send buy (idx 9)"


if __name__ == "__main__":
    try:
        test_farm_calls_bridge_farm_not_equip_buy()
        print("GREEN: farm maps to bridge FARM action")
    except AssertionError as e:
        print("RED:", e)
