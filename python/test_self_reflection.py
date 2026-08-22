"""Tests for SelfReflection — the 'делал выводы' loop."""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from self_reflection import SelfReflection


def _rec(step, action, verdict="success", hp=1.0, deaths=0, qprog=5, cell="0_0",
         reward=0.1, kills=0):
    return {"step": step, "action": action, "verdict": verdict, "hp": hp,
            "deaths": deaths, "qprog": qprog, "cell": cell, "reward": reward,
            "kills": kills}


def _fresh(tmpdir):
    return SelfReflection(path=os.path.join(tmpdir, "refl.json"))


def test_death_cluster_detected(tmp_path=None):
    import tempfile
    td = tempfile.mkdtemp()
    r = _fresh(td)
    step = 0
    deaths = 400
    for i in range(40):
        step += 1
        if i % 10 == 9:
            deaths += 1
        r.observe(_rec(step, "farm", deaths=deaths, cell="-2_-3"))
    concl = r.reflect()
    kinds = [c["kind"] for c in concl]
    assert "DEATH_CLUSTER" in kinds, concl
    dc = next(c for c in concl if c["kind"] == "DEATH_CLUSTER")
    assert dc["key"].startswith("death:"), dc


def test_action_saturation_detected():
    td = tempfile.mkdtemp()
    r = _fresh(td)
    for i in range(50):
        r.observe(_rec(i, "turn_in_quest", verdict="FAILURE", reward=0.0))
    concl = r.reflect()
    kinds = [c["kind"] for c in concl]
    assert "ACTION_SATURATION" in kinds, concl
    sat = next(c for c in concl if c["kind"] == "ACTION_SATURATION")
    assert sat["key"] == "spin:turn_in_quest", sat


def test_quest_stall_detected():
    td = tempfile.mkdtemp()
    r = _fresh(td)
    for i in range(50):
        r.observe(_rec(i, "farm" if i % 2 else "cast_fireball", qprog=8))
    concl = r.reflect()
    kinds = [c["kind"] for c in concl]
    assert "QUEST_STALL" in kinds, concl


def test_vendor_cycle_positive():
    td = tempfile.mkdtemp()
    r = _fresh(td)
    for i in range(40):
        r.observe(_rec(i, "sell_junk", verdict="SUCCESS", reward=0.4))
    concl = r.reflect()
    assert any(c["kind"] == "VENDOR_CYCLE_OK" for c in concl), concl


def test_journal_persists_and_hints_readable():
    td = tempfile.mkdtemp()
    r1 = _fresh(td)
    for i in range(45):
        r1.observe(_rec(i, "loot", verdict="FAILURE", reward=0.0))
    r1.reflect()
    # new instance reads the same file
    r2 = _fresh(td)
    hints = r2.hints()
    assert len(hints) > 0, "hints must survive restart"
