"""
RED -> GREEN: verify_heal must accept 'success' when regen (out-of-combat
auto-tick) raised HP. Current implementation returns 'failure' if
h1 <= h0 even though the bridge case 7's regen path ran.

Observed: live agent run 11 heal->failure in a row at hp 0.02-0.22, all
when player was out of combat. Real cause: regen was a slow tick (one
+1 HP per bridge step), and a single snapshot inside one agent cycle
captured h0=22 and h1=22 (no change in same tick), so the verifier
flagged every regen attempt as failure. Agent got stuck in heal loop.

Fix: verify_heal should be 'success' if h1 > h0 OR h1 >= 0.9 * maxHp.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verifiers_py as V


def test_heal_success_when_hp_rises():
    """h1 > h0 -> success (potion, food, or regen)."""
    c = {
        "before": {"player": {"hp": 20, "maxHp": 100}, "inventory": []},
        "after":  {"player": {"hp": 25, "maxHp": 100}, "inventory": []},
    }
    assert V.verify_heal(c) == "success", f"expected success, got {V.verify_heal(c)}"


def test_heal_success_when_hp_at_max():
    """h1 >= maxHp -> success (full heal)."""
    c = {
        "before": {"player": {"hp": 80, "maxHp": 100}, "inventory": []},
        "after":  {"player": {"hp": 100, "maxHp": 100}, "inventory": []},
    }
    assert V.verify_heal(c) == "success"


def test_heal_success_when_regen_at_high_pct():
    """Regen (out-of-combat) raised HP from 80 to 92 -> 92% > 90% threshold."""
    c = {
        "before": {"player": {"hp": 80, "maxHp": 100}, "inventory": []},
        "after":  {"player": {"hp": 92, "maxHp": 100}, "inventory": []},
    }
    # even though h0==80, h1==92: 92 >= 0.9*100 = 90 -> success
    assert V.verify_heal(c) == "success"


def test_heal_failure_when_no_supplies_and_hp_stuck():
    """h0 == h1 AND in_combat=True (regen blocked) AND no potion -> failure."""
    c = {
        "before": {"player": {"hp": 5, "maxHp": 100, "inCombat": True}, "inventory": []},
        "after":  {"player": {"hp": 5, "maxHp": 100, "inCombat": True}, "inventory": []},
    }
    assert V.verify_heal(c) == "failure"


def test_heal_success_when_regen_paused_no_progress():
    """h0 == h1, in_combat=False, h1>0 -> success (regen path ran, snapshot timing)."""
    c = {
        "before": {"player": {"hp": 22, "maxHp": 100, "inCombat": False}, "inventory": []},
        "after":  {"player": {"hp": 22, "maxHp": 100, "inCombat": False}, "inventory": []},
    }
    assert V.verify_heal(c) == "success"


if __name__ == "__main__":
    tests = [
        test_heal_success_when_hp_rises,
        test_heal_success_when_hp_at_max,
        test_heal_success_when_regen_at_high_pct,
        test_heal_failure_when_no_supplies_and_hp_stuck,
        test_heal_success_when_regen_paused_no_progress,
    ]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
