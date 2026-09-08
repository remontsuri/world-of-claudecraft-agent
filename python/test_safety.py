"""test_safety.py — Safety gate for the arbitration layer.

Covers all 4 cases of safety_check():
  1. "respawn" when player dead
  2. "heal" when hp < 0.2 AND has potions/food
  3. "noop" when hp < 0.2 AND no potions (wait for regen)
  4. None when hp >= 0.2

Also verifies policy.py no longer has the survival gate (lines 588-593 removed).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from safety import safety_check, _has_healing


# ---- helpers ----

def _ws(hp_frac, inv_by_id=None):
    """Build a minimal world_state dict for safety_check()."""
    ws = {"hp_frac": hp_frac}
    if inv_by_id is not None:
        ws["inv_by_id"] = inv_by_id
        ws["inventory_by_id"] = inv_by_id
    return ws


def _info(dead=False, hp=100, maxHp=100, inv_by_id=None):
    """Build a minimal info dict for safety_check()."""
    info = {
        "player": {"dead": dead, "hp": hp, "maxHp": maxHp},
    }
    if inv_by_id is not None:
        info["inv_by_id"] = inv_by_id
        info["inventory_by_id"] = inv_by_id
    return info


# ---- tests ----

def test_safety_returns_respawn_when_dead():
    """Case 1: player dead → safety_check returns 'respawn'."""
    info = _info(dead=True, hp=0, maxHp=100)
    ws = _ws(0.0)
    result = safety_check(info, ws)
    assert result == "respawn", f"Expected 'respawn', got {result!r}"


def test_safety_returns_heal_at_low_hp_with_potions():
    """Case 2: hp < 0.2 AND has potions → safety_check returns 'heal'."""
    info = _info(dead=False, hp=15, maxHp=100,
                 inv_by_id={"minor_healing_potion": 3})
    ws = _ws(0.15, inv_by_id={"minor_healing_potion": 3})
    result = safety_check(info, ws)
    assert result == "heal", f"Expected 'heal', got {result!r}"


def test_safety_returns_heal_at_low_hp_with_food():
    """Case 2b: hp < 0.2 AND has food (bread) → safety_check returns 'heal'."""
    info = _info(dead=False, hp=10, maxHp=100,
                 inv_by_id={"baked_bread": 2})
    ws = _ws(0.10, inv_by_id={"baked_bread": 2})
    result = safety_check(info, ws)
    assert result == "heal", f"Expected 'heal', got {result!r}"


def test_safety_returns_noop_at_low_hp_no_potions():
    """Case 3: hp < 0.2 AND no potions → safety_check returns 'noop'."""
    info = _info(dead=False, hp=15, maxHp=100,
                 inv_by_id={"rough_hide": 5, "game_meat": 2})
    ws = _ws(0.15, inv_by_id={"rough_hide": 5, "game_meat": 2})
    result = safety_check(info, ws)
    assert result == "noop", f"Expected 'noop', got {result!r}"


def test_safety_returns_noop_at_low_hp_empty_bag():
    """Case 3b: hp < 0.2 AND empty bag → safety_check returns 'noop'."""
    info = _info(dead=False, hp=10, maxHp=100)
    ws = _ws(0.10)
    result = safety_check(info, ws)
    assert result == "noop", f"Expected 'noop', got {result!r}"


def test_safety_returns_none_at_safe_hp():
    """Case 4: hp >= 0.2 → safety_check returns None (safe to proceed)."""
    info = _info(dead=False, hp=50, maxHp=100)
    ws = _ws(0.5)
    result = safety_check(info, ws)
    assert result is None, f"Expected None, got {result!r}"


def test_safety_returns_none_at_full_hp():
    """Case 4b: hp = 1.0 → safety_check returns None."""
    info = _info(dead=False, hp=100, maxHp=100)
    ws = _ws(1.0)
    result = safety_check(info, ws)
    assert result is None, f"Expected None, got {result!r}"


def test_safety_boundary_at_exactly_02():
    """Case 4c: hp exactly 0.2 → safety_check returns None (boundary is < 0.2)."""
    info = _info(dead=False, hp=20, maxHp=100)
    ws = _ws(0.2)
    result = safety_check(info, ws)
    assert result is None, f"Expected None at hp=0.2, got {result!r}"


def test_safety_just_below_boundary():
    """Case 2c: hp just below 0.2 (0.199) with potions → 'heal'."""
    info = _info(dead=False, hp=19, maxHp=100,
                 inv_by_id={"minor_healing_potion": 1})
    ws = _ws(0.199, inv_by_id={"minor_healing_potion": 1})
    result = safety_check(info, ws)
    assert result == "heal", f"Expected 'heal' at hp=0.199, got {result!r}"


# ---- _has_healing tests ----

def test_has_healing_with_potion():
    """_has_healing detects potions by name pattern."""
    info = _info(inv_by_id={"minor_healing_potion": 2})
    ws = {}
    assert _has_healing(info, ws) is True


def test_has_healing_with_food():
    """_has_healing detects food items."""
    info = {}
    ws = {"inv_by_id": {"baked_bread": 3, "spring_water": 1}}
    assert _has_healing(info, ws) is True


def test_has_healing_false_for_crafting_materials():
    """_has_healing returns False for non-healing items."""
    info = _info(inv_by_id={"rough_hide": 5, "game_meat": 2, "copper_ore": 3})
    ws = {}
    assert _has_healing(info, ws) is False


def test_has_healing_false_for_empty_inventory():
    """_has_healing returns False when inventory is empty."""
    info = _info(inv_by_id={})
    ws = {}
    assert _has_healing(info, ws) is False


def test_has_healing_false_for_missing_keys():
    """_has_healing returns False when no inventory keys exist."""
    info = _info()
    ws = {}
    assert _has_healing(info, ws) is False


# ---- policy.py regression test ----

def test_policy_no_survival_gate():
    """policy.py must NOT contain the survival gate (lines 588-593 removed).

    The retreat option (quest_accepted AND danger AND hp>=0.35 → append RETURN
    in _candidates) was a hardcoded safety override that belongs in the
    arbitration layer now.

    NOTE: the phase_return logic at line ~851 (RETURN_TO_GIVER phase +
    hp>=0.35 → return_to_giver) is DIFFERENT — it's a phase gate override,
    not a survival gate, and is Phase 4's job to remove. We only check that
    the specific _candidates survival gate pattern is gone.
    """
    policy_path = os.path.join(os.path.dirname(__file__), "policy.py")
    with open(policy_path, encoding="utf-8") as f:
        source = f.read()

    # The specific pattern that was the survival gate in _candidates:
    # "quest_accepted and ws.get("danger")" appeared in the removed block
    # inside _candidates method. Now "quest_accepted" is still used elsewhere
    # (phase filtering), but the specific combination with "danger" AND "0.35"
    # in _candidates context is gone.
    # Check that the danger-based retreat gate in _candidates is removed:
    assert "quest_accepted and ws.get(\"danger\")" not in source, (
        "policy.py still contains the survival gate — should be removed"
    )


def test_policy_still_has_bag_survival_sell():
    """policy.py must STILL have the bag survival sell (Phase 4 will handle it).

    Bag survival sell is economy, NOT safety — it stays in policy for now.
    """
    policy_path = os.path.join(os.path.dirname(__file__), "policy.py")
    with open(policy_path, encoding="utf-8") as f:
        source = f.read()

    assert "bag_survival_sell" in source or "bag_survival" in source, (
        "policy.py lost the bag survival sell — it should remain for Phase 4"
    )
    assert "bag_slots_sell >= bag_capacity - 3" in source, (
        "policy.py lost the bag capacity check — it should remain for Phase 4"
    )


if __name__ == "__main__":
    # Run all tests and report
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
