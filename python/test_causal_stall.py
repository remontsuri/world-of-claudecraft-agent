"""Tests for SelfReflection causal chain learning (STREAM J4)."""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from self_reflection import SelfReflection


def _fresh(td):
    return SelfReflection(path=os.path.join(td, "refl.json"))


def _rec(step, action, verdict="success", hp=1.0, deaths=0, qprog=5, cell="0_0",
         reward=0.1, kills=0, target_mob_id=None, target_hp=None,
         target_dead=False, loot_attempted=False, loot_success=False):
    """Build a step record with all fields (including STREAM J4 target info)."""
    return {
        "step": step, "action": action, "verdict": verdict, "hp": hp,
        "deaths": deaths, "qprog": qprog, "cell": cell, "reward": reward,
        "kills": kills,
        # STREAM J4 fields
        "target_mob_id": target_mob_id,
        "target_hp": target_hp,
        "target_dead": target_dead,
        "loot_attempted": loot_attempted,
        "loot_success": loot_success,
    }


# ---- Test 1: CAUSAL_STALL detected on specific mob --------------------------

def test_causal_stall_detected_on_mob():
    """When mob#152 is farmed, dies, looted, but qprog frozen -> CAUSAL_STALL."""
    td = tempfile.mkdtemp()
    r = _fresh(td)
    # Feed 40 steps: farming mob#152, it dies, loot attempted, qprog stays at 5
    for i in range(40):
        if i < 20:
            # alive, farming
            r.observe(_rec(i, "farm", qprog=5, target_mob_id="152", target_hp=max(0, 20 - i)))
        elif i == 20:
            # mob dies
            r.observe(_rec(i, "farm", qprog=5, target_mob_id="152", target_hp=0, target_dead=True))
        elif i == 21:
            # loot attempt
            r.observe(_rec(i, "loot", qprog=5, target_mob_id="152", target_hp=0,
                             target_dead=True, loot_attempted=True, loot_success=True))
        else:
            # nothing changes
            r.observe(_rec(i, "farm", qprog=5, target_mob_id="152", target_hp=0, target_dead=True))

    concl = r.reflect()
    kinds = [c["kind"] for c in concl]
    assert "CAUSAL_STALL" in kinds, f"Expected CAUSAL_STALL, got: {kinds}"
    cs = next(c for c in concl if c["kind"] == "CAUSAL_STALL")
    assert "152" in cs["key"], f"Expected mob ID in key, got: {cs['key']}"
    assert cs["key"] == "exclude:mob#152", f"Wrong key: {cs['key']}"


# ---- Test 2: Causal chain structure -----------------------------------------

def test_causal_chain_has_all_links():
    """CAUSAL_STALL conclusion must contain 7-link causal chain."""
    td = tempfile.mkdtemp()
    r = _fresh(td)
    for i in range(40):
        if i < 15:
            r.observe(_rec(i, "farm", qprog=3, target_mob_id="wolf_alpha", target_hp=10))
        elif i == 15:
            r.observe(_rec(i, "farm", qprog=3, target_mob_id="wolf_alpha", target_hp=0, target_dead=True))
        elif i == 16:
            r.observe(_rec(i, "loot", qprog=3, target_mob_id="wolf_alpha", target_hp=0,
                             target_dead=True, loot_attempted=True, loot_success=True))
        else:
            r.observe(_rec(i, "explore", qprog=3))

    concl = r.reflect()
    cs = next(c for c in concl if c["kind"] == "CAUSAL_STALL")
    chain = cs.get("causal_chain", [])
    assert len(chain) >= 3, f"Chain too short: {chain}"
    # Verify all 7 nodes present
    expected_nodes = {"observation", "effect", "action", "failure", "cause", "lesson", "strategy"}
    actual_nodes = {link.get("node") for link in chain}
    assert actual_nodes == expected_nodes, f"Missing nodes: {expected_nodes - actual_nodes}"


# ---- Test 3: NO false positive when qprog advances --------------------------

def test_no_causal_stall_when_progress():
    """When qprog changes after farming, NO CAUSAL_STALL."""
    td = tempfile.mkdtemp()
    r = _fresh(td)
    for i in range(40):
        if i < 20:
            r.observe(_rec(i, "farm", qprog=3, target_mob_id="forest_wolf", target_hp=max(0, 20 - i)))
        elif i == 20:
            r.observe(_rec(i, "farm", qprog=4, target_mob_id="forest_wolf", target_hp=0, target_dead=True))
        else:
            r.observe(_rec(i, "farm", qprog=5, target_mob_id="forest_wolf", target_hp=0, target_dead=True))

    concl = r.reflect()
    kinds = [c["kind"] for c in concl]
    assert "CAUSAL_STALL" not in kinds, f"False positive: {kinds}"


# ---- Test 4: NO false positive when mob doesn't die ------------------------

def test_no_causal_stall_when_mob_alive():
    """When target mob never dies, NO CAUSAL_STALL."""
    td = tempfile.mkdtemp()
    r = _fresh(td)
    for i in range(40):
        r.observe(_rec(i, "farm", qprog=5, target_mob_id="greyjaw", target_hp=15))

    concl = r.reflect()
    kinds = [c["kind"] for c in concl]
    assert "CAUSAL_STALL" not in kinds, f"False positive on alive mob: {kinds}"


# ---- Test 5: Hint is machine-actionable -------------------------------------

def test_causal_stall_hint_excludes_target():
    """CAUSAL_STALL hint must be 'exclude_target' so policy can act on it."""
    td = tempfile.mkdtemp()
    r = _fresh(td)
    for i in range(40):
        if i < 20:
            r.observe(_rec(i, "farm", qprog=5, target_mob_id="boar", target_hp=max(0, 20 - i)))
        else:
            r.observe(_rec(i, "farm", qprog=5, target_mob_id="boar", target_hp=0, target_dead=True))

    concl = r.reflect()
    cs = next(c for c in concl if c["kind"] == "CAUSAL_STALL")
    assert cs["hint"] == "exclude_target", f"Wrong hint: {cs['hint']}"
    assert "target_mob_id" in cs, "Must carry target_mob_id for policy to use"
    assert cs["target_mob_id"] == "boar"


# ---- Test 6: Multiple mobs - only the bad one is flagged --------------------

def test_causal_stall_flags_only_bad_mob():
    """When one mob advances quest and another doesn't, only the bad one is excluded."""
    td = tempfile.mkdtemp()
    r = _fresh(td)
    for i in range(40):
        if i < 15:
            # Good mob: dies AND qprog advances
            r.observe(_rec(i, "farm", qprog=min(5, 3 + i // 5), target_mob_id="quest_wolf",
                             target_hp=max(0, 15 - i)))
        elif i == 15:
            r.observe(_rec(i, "farm", qprog=5, target_mob_id="quest_wolf",
                             target_hp=0, target_dead=True))
        else:
            # Bad mob: dies but qprog stays at 5
            r.observe(_rec(i, "farm", qprog=5, target_mob_id="random_boar",
                             target_hp=0, target_dead=True))

    concl = r.reflect()
    cs_list = [c for c in concl if c["kind"] == "CAUSAL_STALL"]
    assert len(cs_list) >= 1, f"Expected at least 1 CAUSAL_STALL, got: {cs_list}"
    # The bad mob must be flagged
    bad_mob_flagged = any("random_boar" in c["key"] for c in cs_list)
    assert bad_mob_flagged, f"Bad mob not flagged: {cs_list}"
    # The good mob must NOT be flagged
    good_mob_flagged = any("quest_wolf" in c["key"] for c in cs_list)
    assert not good_mob_flagged, f"Good mob incorrectly flagged: {cs_list}"


# ---- Test 7: Journal persistence -------------------------------------------

def test_causal_stall_persists_to_journal():
    """CAUSAL_STALL conclusion is written to journal and survives restart."""
    td = tempfile.mkdtemp()
    r1 = _fresh(td)
    for i in range(40):
        if i < 20:
            r1.observe(_rec(i, "farm", qprog=5, target_mob_id="mob_x", target_hp=max(0, 20 - i)))
        else:
            r1.observe(_rec(i, "farm", qprog=5, target_mob_id="mob_x", target_hp=0, target_dead=True))

    r1.reflect()
    assert len(r1.journal) > 0, "Journal empty after reflect"

    # New instance reads same file
    r2 = _fresh(td)
    hints = r2.hints()
    assert any(k.startswith("exclude:mob#") for k in hints), f"No exclude hint in: {hints}"


if __name__ == "__main__":
    test_causal_stall_detected_on_mob()
    print("PASS: test_causal_stall_detected_on_mob")

    test_causal_chain_has_all_links()
    print("PASS: test_causal_chain_has_all_links")

    test_no_causal_stall_when_progress()
    print("PASS: test_no_causal_stall_when_progress")

    test_no_causal_stall_when_mob_alive()
    print("PASS: test_no_causal_stall_when_mob_alive")

    test_causal_stall_hint_excludes_target()
    print("PASS: test_causal_stall_hint_excludes_target")

    test_causal_stall_flags_only_bad_mob()
    print("PASS: test_causal_stall_flags_only_bad_mob")

    test_causal_stall_persists_to_journal()
    print("PASS: test_causal_stall_persists_to_journal")

    print("\nAll STREAM J4 causal chain tests PASSED.")
