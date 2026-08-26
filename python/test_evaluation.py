"""TDD tests for the autonomy evaluation suite (evaluation.py).

Run from the python/ directory:
    C:/Users/vladc/AppData/Local/Programs/Python/Python312/python.exe test_evaluation.py

These tests must FAIL before evaluation.py exists, then PASS after.
"""
import json
import os
import tempfile
import unittest

import evaluation


def _rec(**kw):
    """Build a minimal record with sane defaults."""
    base = {
        "step": 0,
        "pid": 1,
        "action": "farm",
        "verdict": "success",
        "dist": 10.0,
        "kills": 0,
        "deaths": 0,
        "qprog": 0,
    }
    base.update(kw)
    return base


def _perfect_run(n=12):
    """A run that should score ~1.0: every attempt succeeds, real progress
    is made every step, no stuck loops, no inconclusive verdicts."""
    recs = []
    actions = ["accept_quest", "turn_in_quest", "sell_junk", "buy", "farm", "farm",
               "farm", "farm", "farm", "farm", "farm", "farm"]
    for i, a in enumerate(actions[:n]):
        recs.append(_rec(
            step=i,
            action=a,
            verdict="success",
            dist=float(10 - i),       # strictly decreasing -> nav frac 1.0
            kills=i,                  # strictly increasing -> kills_delta > 0
            deaths=0,                 # no deaths
            qprog=i,                  # strictly increasing -> progress
        ))
    return recs


def _all_inconclusive_run(n=10):
    """A run that should score ~0.0: every verdict is inconclusive, no quest/
    economy/combat/nav data at all, and one repeated action with no progress
    (so a long no-progress loop is detected)."""
    recs = []
    for i in range(n):
        recs.append({
            "step": i,
            "pid": 7,
            "action": "farm",          # repeated, never succeeds -> long no-progress run
            "verdict": "inconclusive", # never 'success'
            # intentionally no dist/kills/deaths/qprog -> those categories None
        })
    return recs


class TestEvaluate(unittest.TestCase):

    def test_perfect_run_scores_near_one(self):
        score = evaluation.evaluate(_perfect_run())
        self.assertIsNotNone(score["autonomy_score"])
        self.assertGreater(score["autonomy_score"], 0.95,
                          "perfect run should score near 1.0, got %r" % score["autonomy_score"])

    def test_all_inconclusive_scores_near_zero(self):
        score = evaluation.evaluate(_all_inconclusive_run())
        self.assertIsNotNone(score["autonomy_score"])
        self.assertLess(score["autonomy_score"], 0.05,
                        "all-inconclusive run should score near 0.0, got %r" % score["autonomy_score"])

    def test_accept_rate_two_of_three(self):
        recs = [
            _rec(step=0, action="accept_quest", verdict="success"),
            _rec(step=1, action="accept_quest", verdict="success"),
            _rec(step=2, action="accept_quest", verdict="failure"),
        ]
        score = evaluation.evaluate(recs)
        self.assertAlmostEqual(score["quest"]["accept_rate"], 2.0 / 3.0, places=6)

    def test_empty_does_not_raise(self):
        score = evaluation.evaluate([])
        self.assertIsInstance(score, dict)
        # no data -> no subscore -> autonomy_score None, but no exception
        self.assertIsNone(score["autonomy_score"])

    def test_no_attempts_reported_as_none_not_zero(self):
        # A run with zero quest/economy attempts: those rates must be None and
        # excluded from the average, never counted as 0.
        recs = [_rec(step=i, action="farm", verdict="success", kills=i, qprog=i,
                     dist=float(10 - i)) for i in range(5)]
        score = evaluation.evaluate(recs)
        self.assertIsNone(score["quest"]["accept_rate"])
        self.assertIsNone(score["quest"]["turn_in_rate"])
        self.assertIsNone(score["economy"]["sell_rate"])
        self.assertIsNone(score["economy"]["buy_rate"])
        # autonomy_score should still be a real number (not None) because other
        # categories have data.
        self.assertIsNotNone(score["autonomy_score"])

    def test_no_division_by_zero_on_single_record(self):
        recs = [_rec(step=0, action="farm", verdict="success", kills=0, qprog=0, dist=5.0)]
        score = evaluation.evaluate(recs)  # must not raise ZeroDivisionError
        self.assertIsInstance(score, dict)


class TestLoadRun(unittest.TestCase):

    def _write_tmp(self, lines):
        fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="eval_test_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(ln + "\n")
        return path

    def test_skips_malformed_lines(self):
        path = self._write_tmp([
            '{"pid": 1, "action": "farm", "verdict": "success"}',
            "this is not json at all ===",
            "=== another summary line ===",
            '{"pid": 1, "action": "sell_junk", "verdict": "failure"}',
            "{broken json",
            '{"pid": 1, "action": "accept_quest", "verdict": "success"}',
        ])
        try:
            recs = evaluation.load_run(path)
            self.assertEqual(len(recs), 3)
            for r in recs:
                self.assertIsInstance(r, dict)
        finally:
            os.remove(path)

    def test_pid_none_returns_last_run_only(self):
        # First-appearance order: pid1@0, pid2@1, pid3@4 (last run).
        path = self._write_tmp([
            '{"pid": 1, "action": "a", "verdict": "success"}',
            '{"pid": 2, "action": "b", "verdict": "success"}',
            '{"pid": 1, "action": "c", "verdict": "failure"}',
            "garbage line that is not json",
            '{"pid": 3, "action": "d", "verdict": "inconclusive"}',
        ])
        try:
            recs = evaluation.load_run(path)  # pid=None
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0]["pid"], 3)
        finally:
            os.remove(path)

    def test_pid_filter_returns_only_that_run(self):
        path = self._write_tmp([
            '{"pid": 1, "action": "a", "verdict": "success"}',
            '{"pid": 2, "action": "b", "verdict": "success"}',
            '{"pid": 1, "action": "c", "verdict": "failure"}',
        ])
        try:
            recs = evaluation.load_run(path, pid=1)
            self.assertEqual(len(recs), 2)
            self.assertTrue(all(r["pid"] == 1 for r in recs))
        finally:
            os.remove(path)


class TestFormatReport(unittest.TestCase):

    def test_format_report_returns_string(self):
        score = evaluation.evaluate(_perfect_run())
        rep = evaluation.format_report(score)
        self.assertIsInstance(rep, str)
        self.assertGreater(len(rep), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
