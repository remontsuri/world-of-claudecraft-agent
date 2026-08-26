"""Тесты Autonomy Benchmark (ARCHITECTURE.md §15).

Запуск: cd python && python -m pytest test_evaluation.py -v
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evaluation import load_run, evaluate, format_report


def _r(step, action, verdict="success", pid=1, **kw):
    rec = {"step": step, "pid": pid, "action": action, "verdict": verdict}
    rec.update(kw)
    return rec


# ------------------------------------------------------------------- evaluate

def test_empty_records_do_not_raise():
    s = evaluate([])
    assert s["total_steps"] == 0
    assert s["autonomy_score"] == 0.0


def test_perfect_run_scores_high():
    recs = []
    for i in range(20):
        recs.append(_r(i, "farm", "success", kills=i, deaths=0, qprog=min(8, i),
                       dist=30 - i, xp=i))
    recs.append(_r(20, "accept_quest", "success", kills=20, deaths=0, qprog=8,
                   dist=5, xp=20))
    recs.append(_r(21, "turn_in_quest", "success", kills=20, deaths=0, qprog=8,
                   dist=4, xp=30, quests_done=1))
    s = evaluate(recs)
    assert s["autonomy_score"] > 0.8, s["components"]


def test_all_inconclusive_scores_low():
    recs = [_r(i, "farm", "inconclusive", kills=0, deaths=0, qprog=0)
            for i in range(30)]
    s = evaluate(recs)
    assert s["autonomy_score"] < 0.3, s["components"]
    assert s["loop_health"]["inconclusive_share"] == 1.0


def test_accept_rate_two_of_three():
    recs = [_r(0, "accept_quest", "success"),
            _r(1, "accept_quest", "failure"),
            _r(2, "accept_quest", "success")]
    s = evaluate(recs)
    assert abs(s["quest"]["accept_rate"] - 2.0 / 3.0) < 1e-9
    assert s["quest"]["accept_attempts"] == 3


def test_category_without_attempts_is_none_and_excluded():
    recs = [_r(i, "farm", "success", kills=i) for i in range(12)]
    s = evaluate(recs)
    assert s["components"]["economy_buy"] is None
    assert s["components"]["quest_accept"] is None
    # None-компоненты не тянут score вниз как нули
    assert s["autonomy_score"] > 0.0


def test_no_division_by_zero_on_single_record():
    s = evaluate([_r(0, "farm", "success")])
    assert isinstance(s["autonomy_score"], float)


def test_deaths_reduce_survival_component():
    good = [_r(i, "farm", "success", kills=i, deaths=0) for i in range(20)]
    bad = [_r(i, "farm", "success", kills=i, deaths=i // 4) for i in range(20)]
    assert (evaluate(good)["components"]["combat_survival"]
            > evaluate(bad)["components"]["combat_survival"])


def test_max_no_progress_run_detected():
    recs = [_r(i, "buy", "inconclusive", kills=0, qprog=0, deaths=0, xp=0)
            for i in range(15)]
    s = evaluate(recs)
    assert s["loop_health"]["max_no_progress_run"] >= 14
    assert s["components"]["loop_health"] < 1.0


def test_progress_breaks_no_progress_run():
    recs = [_r(i, "farm", "success", kills=i, qprog=0, deaths=0, xp=i)
            for i in range(15)]
    s = evaluate(recs)
    assert s["loop_health"]["max_no_progress_run"] <= 2


def test_navigation_fraction_counts_only_decreases():
    recs = [_r(0, "explore", dist=30.0), _r(1, "explore", dist=20.0),
            _r(2, "explore", dist=25.0), _r(3, "explore", dist=10.0)]
    s = evaluate(recs)
    # 3 пары: 30->20 (да), 20->25 (нет), 25->10 (да)
    assert abs(s["navigation"]["dist_improved_fraction"] - 2.0 / 3.0) < 1e-9


def test_navigation_none_when_no_dist_data():
    s = evaluate([_r(0, "farm"), _r(1, "farm")])
    assert s["navigation"]["dist_improved_fraction"] is None


# ------------------------------------------------------------------- load_run

def _write(lines):
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8")
    for l in lines:
        fh.write(l + "\n")
    fh.close()
    return fh.name


def test_load_run_skips_malformed_lines():
    path = _write([
        json.dumps(_r(0, "farm", pid=7)),
        "  action_dist = {'farm': '100%'}",
        "not json at all",
        "",
        json.dumps(_r(1, "loot", pid=7)),
    ])
    try:
        recs = load_run(path)
        assert len(recs) == 2
        assert [r["action"] for r in recs] == ["farm", "loot"]
    finally:
        os.unlink(path)


def test_load_run_returns_only_last_run():
    path = _write([
        json.dumps(_r(0, "farm", pid=1)),
        json.dumps(_r(1, "farm", pid=1)),
        json.dumps(_r(0, "loot", pid=2)),
        json.dumps(_r(1, "loot", pid=2)),
        json.dumps(_r(2, "loot", pid=2)),
    ])
    try:
        recs = load_run(path)
        assert len(recs) == 3
        assert all(r["pid"] == 2 for r in recs)
    finally:
        os.unlink(path)


def test_load_run_explicit_pid():
    path = _write([
        json.dumps(_r(0, "farm", pid=1)),
        json.dumps(_r(0, "loot", pid=2)),
    ])
    try:
        recs = load_run(path, pid=1)
        assert len(recs) == 1 and recs[0]["action"] == "farm"
    finally:
        os.unlink(path)


def test_load_run_missing_file_returns_empty():
    assert load_run("D:/definitely/not/here.jsonl") == []


# --------------------------------------------------------------------- report

def test_format_report_contains_score_and_sections():
    txt = format_report(evaluate([_r(i, "farm", "success", kills=i)
                                 for i in range(12)]))
    assert "AUTONOMY SCORE" in txt
    assert "QUEST" in txt and "ECONOMY" in txt and "COMBAT" in txt
    assert "n/a" in txt          # категории без попыток честно помечены


def test_format_report_on_empty_does_not_raise():
    assert "AUTONOMY SCORE" in format_report(evaluate([]))
