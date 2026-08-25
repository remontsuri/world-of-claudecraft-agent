"""test_failure_analyzer.py — TDD для failure_analyzer.py (план 2026-08-24, п.4).

Контракт из плана: каждая FAILURE -> {action, failure, cause, fix, retry,
context}; повторяющиеся причины -> рекомендации; ничего не падает на
пустых/кривых входах.
"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(__file__))


# ---------- classify ----------

def test_success_step_is_ignored():
    from failure_analyzer import classify
    assert classify({"verdict": "SUCCESS", "action": "farm"}) is None
    assert classify({"verdict": "inconclusive", "action": "loot"}) is None


def test_turn_in_too_far_is_interaction_failure():
    from failure_analyzer import classify
    a = classify({"verdict": "FAILURE", "action": "turn_in_quest",
                  "dist": 59.3, "goal": "TURN_IN", "hp": 1.0})
    assert a["failure"] == "INTERACTION_FAILURE"
    assert a["cause"].startswith("too_far")
    assert a["fix"] == "move_closer_then_turn_in"
    assert a["retry"] is True
    assert a["context"]["dist"] == 59.3


def test_turn_in_close_range_is_quest_failure():
    """Фантомный ready / cadence / bags — квестовая проблема, не дистанция."""
    from failure_analyzer import classify
    a = classify({"verdict": "FAILURE", "action": "turn_in_quest",
                  "dist": 2.1, "goal": "TURN_IN"})
    assert a["failure"] == "QUEST_FAILURE"
    assert "rejected" in a["cause"]


def test_env_error_is_bridge_failure():
    from failure_analyzer import classify
    a = classify({"verdict": "ENV_ERROR", "kind": "ENV_ERROR", "action": "step"})
    assert a["failure"] == "BRIDGE_FAILURE"
    assert a["retry"] is True


def test_timeout_marker():
    from failure_analyzer import classify
    a = classify({"verdict": "FAILURE", "action": "farm", "error": "command timeout after 90ms"})
    assert a["failure"] == "TIMEOUT_FAILURE"


def test_low_hp_survival_failure():
    from failure_analyzer import classify
    a = classify({"verdict": "FAILURE", "action": "return_to_giver", "hp": 0.18, "dist": 30.0})
    assert a["failure"] == "SURVIVAL_FAILURE"
    assert a["fix"] == "heal_or_retreat_first"


def test_combat_failure_for_farm():
    from failure_analyzer import classify
    a = classify({"verdict": "FAILURE", "action": "farm", "hp": 0.9})
    assert a["failure"] == "COMBAT_FAILURE"


def test_garbage_input_does_not_crash():
    from failure_analyzer import classify
    assert classify(None) is None
    assert classify({}) is None
    assert classify("junk") is None


# ---------- FailureAnalyzer: накопление и рекомендации ----------

def _tmp_analyzer(tmp_path):
    from failure_analyzer import FailureAnalyzer
    return FailureAnalyzer(path=os.path.join(str(tmp_path), "fa.json"))


def test_observe_accumulates_and_recommends(tmp_path):
    fa = _tmp_analyzer(tmp_path)
    for _ in range(5):
        fa.observe_step({"verdict": "FAILURE", "action": "turn_in_quest",
                         "dist": 60.0, "goal": "TURN_IN"})
    recs = fa.recommendations(min_count=3)
    assert len(recs) >= 1
    top = recs[0]
    assert top["action"] == "turn_in_quest"
    assert top["count"] == 5
    assert top["fix"] == "move_closer_then_turn_in"


def test_save_load_roundtrip(tmp_path):
    p = os.path.join(str(tmp_path), "fa.json")
    from failure_analyzer import FailureAnalyzer
    fa = FailureAnalyzer(path=p)
    fa.observe_step({"verdict": "FAILURE", "action": "sell_junk", "hp": 1.0})
    fa.save()
    fa2 = FailureAnalyzer(path=p)
    assert sum(fa2.causes.values()) == 1


def test_summary_line(tmp_path):
    fa = _tmp_analyzer(tmp_path)
    assert fa.summary_line() == "failures=0"
    fa.observe_step({"verdict": "FAILURE", "action": "farm", "hp": 0.9})
    line = fa.summary_line()
    assert "failures=1" in line and "farm" in line
