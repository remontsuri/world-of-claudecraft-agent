"""Тесты автономного контура: skill_contracts, progress, recovery, anti_loop.

Запуск: cd python && python -m pytest test_autonomy_core.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skill_contracts import (get_skill_contract, check_preconditions,
                             verify_postconditions, all_skills)
from progress import detect_progress, classify_outcome
from recovery import get_recovery, ladder_for, RecoveryTracker
from anti_loop import detect_loop, get_loop_recovery, LoopGuard, threshold_for


# ------------------------------------------------------------ skill contracts

def test_buy_contract_has_full_shape():
    c = get_skill_contract("buy")
    assert "vendor_exists" in c["preconditions"]
    assert "money_sufficient" in c["preconditions"]
    assert "inventory_changed" in c["postconditions"]
    assert "no_vendor" in c["failure_reasons"]


def test_every_skill_has_all_four_sections():
    for skill in all_skills():
        c = get_skill_contract(skill)
        assert "preconditions" in c, skill
        assert "action" in c, skill
        assert "postconditions" in c, skill
        assert "failure_reasons" in c, skill


def test_preconditions_fail_without_vendor():
    obs = {"world": {"vendors": 0}, "player": {"copper": 100},
           "inventory": {"free_slots": 5}}
    res = check_preconditions("buy", obs)
    assert res["ok"] is False
    assert "vendor_exists" in res["failed"]


def test_preconditions_pass_with_vendor_in_range():
    obs = {"world": {"vendors": 1, "vendor_distance": 4.0},
           "player": {"copper": 100},
           "inventory": {"free_slots": 5, "buy_item_available": True}}
    res = check_preconditions("buy", obs)
    assert res["ok"] is True, res["failed"]


def test_turn_in_requires_ready_quest():
    obs = {"quest": {"ready": 0, "giver_distance": 3.0},
           "world": {"quest_givers": 1}}
    assert "quest_ready" in check_preconditions("turn_in_quest", obs)["failed"]
    obs["quest"]["ready"] = 1
    assert check_preconditions("turn_in_quest", obs)["ok"] is True


def test_postconditions_buy_success_and_failure():
    ok = verify_postconditions("buy", {"inventory_delta": 1, "copper_delta": -5})
    assert ok["result"] == "SUCCESS"
    bad = verify_postconditions("buy", {"inventory_delta": 0, "copper_delta": 0})
    assert bad["result"] == "FAILURE"
    assert "inventory_changed" in bad["missing"]


def test_postconditions_sell_needs_copper_up():
    assert verify_postconditions("sell_junk", {"copper_delta": 12})["result"] == "SUCCESS"
    assert verify_postconditions("sell_junk", {"copper_delta": 0})["result"] == "FAILURE"


# ------------------------------------------------------------------- progress

def _obs(hp=1.0, copper=0, xp=0, kills=0, free=5, done=0, active=0, ready=0,
         objprog=0, pos=(0.0, 0.0), tdist=999.0, deaths=0):
    return {
        "player": {"hp_fraction": hp, "copper": copper, "xp": xp, "level": 1,
                   "position": list(pos), "deaths": deaths},
        "world": {"kills": kills},
        "inventory": {"free_slots": free},
        "quest": {"done": done, "active": active, "ready": ready,
                  "objective_progress": objprog},
        "navigation": {"target_distance": tdist},
    }


def test_quest_progress_delta():
    p = detect_progress(_obs(ready=0, objprog=2), _obs(ready=1, objprog=3))
    assert p["quest_progress"] == 1
    assert p["quests_ready_delta"] == 1


def test_inventory_delta_sign_is_items_gained():
    # свободных слотов стало меньше -> предмет получен -> +1
    p = detect_progress(_obs(free=5), _obs(free=4))
    assert p["inventory_delta"] == 1


def test_copper_delta_negative_on_purchase():
    p = detect_progress(_obs(copper=20), _obs(copper=15))
    assert p["copper_delta"] == -5


def test_distance_delta_positive_when_approaching():
    p = detect_progress(_obs(tdist=30.0), _obs(tdist=12.0))
    assert p["distance_delta"] == 18.0


def test_classify_no_op_when_nothing_changed():
    p = detect_progress(_obs(), _obs())
    assert classify_outcome(p) == "NO_OP"


def test_classify_success_on_kill():
    p = detect_progress(_obs(kills=0), _obs(kills=1))
    assert classify_outcome(p) == "SUCCESS"


def test_classify_failure_on_death():
    p = detect_progress(_obs(deaths=0), _obs(deaths=1))
    assert classify_outcome(p) == "FAILURE"


# ------------------------------------------------------------------- recovery

def test_recovery_ladder_escalates():
    assert get_recovery("no_vendor", attempt=0) == "find_alternate_vendor"
    assert get_recovery("no_vendor", attempt=1) == "explore_town"
    assert get_recovery("no_vendor", attempt=2) == "abandon_objective"
    # за пределами лестницы — всегда abandon, цикл не зависает
    assert get_recovery("no_vendor", attempt=9) == "abandon_objective"


def test_recovery_known_reasons():
    assert get_recovery("no_tool") == "buy_tool"
    assert get_recovery("hp_too_low") == "retreat_and_heal"
    assert get_recovery("bags_full") == "sell_junk"
    assert get_recovery("mob_too_strong") == "retreat_and_heal"


def test_recovery_unknown_reason_falls_back_to_replan():
    assert get_recovery("something_weird") == "replan"


def test_tracker_counts_and_resets_on_success():
    t = RecoveryTracker(max_attempts=3)
    a = t.next_action("buy", "no_vendor")
    b = t.next_action("buy", "no_vendor")
    assert a["recovery_action"] == "find_alternate_vendor"
    assert b["recovery_action"] == "explore_town"
    assert b["attempt"] == 1
    t.on_success("buy")
    c = t.next_action("buy", "no_vendor")
    assert c["attempt"] == 0


def test_tracker_reports_exhausted():
    t = RecoveryTracker(max_attempts=2)
    t.next_action("gather", "no_tool")
    r = t.next_action("gather", "no_tool")
    assert r["exhausted"] is True


# ------------------------------------------------------------------ anti-loop

def test_buy_loop_detected_without_progress():
    hist = ["buy"] * 3
    prog = [False] * 3
    assert detect_loop(hist, prog) is True
    assert get_loop_recovery("buy") == "cooldown_30_steps"


def test_no_loop_when_progress_present():
    hist = ["farm"] * threshold_for("farm")
    prog = [False] * (threshold_for("farm") - 1) + [True]
    assert detect_loop(hist, prog) is False


def test_no_loop_below_threshold():
    assert detect_loop(["buy", "buy"], [False, False]) is False


def test_guard_trips_and_blocks_action():
    g = LoopGuard()
    for _ in range(3):
        g.observe("buy", made_progress=False, state_key="s1")
    assert g.is_looping() is True
    r = g.trip()
    assert r["recovery_action"] == "cooldown_30_steps"
    assert g.blocked("buy") is True
    assert "buy" not in g.filter_candidates(["buy", "farm"])


def test_guard_filter_never_returns_empty():
    g = LoopGuard()
    for _ in range(3):
        g.observe("buy", made_progress=False)
    g.trip()
    assert g.filter_candidates(["buy"]) == ["buy"]


def test_guard_cooldown_expires():
    g = LoopGuard()
    for _ in range(3):
        g.observe("buy", made_progress=False)
    g.trip()
    for _ in range(31):
        g.observe("farm", made_progress=True)
    assert g.blocked("buy") is False


def test_guard_counts_no_progress_steps():
    g = LoopGuard()
    g.observe("farm", made_progress=True)
    for _ in range(4):
        g.observe("farm", made_progress=False)
    assert g.no_progress_steps() == 4


def test_guard_detects_stuck_state():
    g = LoopGuard()
    for _ in range(30):
        g.observe("explore", made_progress=False, state_key="same_cell")
    assert g.stuck_in_state(30) is True
