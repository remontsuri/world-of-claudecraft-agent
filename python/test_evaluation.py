"""Tests for the autonomy evaluation suite (Task 10)."""
import json
import os
import tempfile
import unittest

import evaluation


def rec(step, action, verdict, **kw):
    r = {
        "step": step,
        "pid": kw.pop("pid", 1),
        "action": action,
        "verdict": verdict,
        "dist": kw.pop("dist", None),
        "kills": kw.pop("kills", 0),
        "deaths": kw.pop("deaths", 0),
        "qprog": kw.pop("qprog", 0),
        "xp": kw.pop("xp", 0),
    }
    r.update(kw)
    return r


def perfect_run(n=10):
    acts = ["accept_quest", "farm", "turn_in_quest", "sell_junk", "buy"]
    out = []
    for i in range(n):
        out.append(rec(i, acts[i % len(acts)], "success",
                       dist=100.0 - i, kills=i, deaths=0, qprog=i, xp=i * 10))
    return out


def inconclusive_run(n=10):
    return [rec(i, "accept_quest", "inconclusive",
                dist=50.0, kills=0, deaths=0, qprog=0, xp=0) for i in range(n)]


class TestEvaluate(unittest.TestCase):
    def test_perfect_run_scores_near_one(self):
        s = evaluation.evaluate(perfect_run())
        self.assertGreaterEqual(s["autonomy_score"], 0.95)
        self.assertLessEqual(s["autonomy_score"], 1.0)

    def test_all_inconclusive_scores_near_zero(self):
        s = evaluation.evaluate(inconclusive_run())
        self.assertLessEqual(s["autonomy_score"], 0.05)
        self.assertGreaterEqual(s["autonomy_score"], 0.0)

    def test_accept_rate_two_thirds(self):
        recs = [
            rec(0, "accept_quest", "success"),
            rec(1, "accept_quest", "SUCCESS"),
            rec(2, "accept_quest", "failure"),
        ]
        s = evaluation.evaluate(recs)
        self.assertAlmostEqual(s["quest"]["accept_rate"], 2.0 / 3.0, places=6)

    def test_empty_records_does_not_raise(self):
        s = evaluation.evaluate([])
        self.assertIsInstance(s, dict)
        self.assertIn("autonomy_score", s)
        self.assertEqual(s["quest"]["accept_rate"], None)
        self.assertEqual(s["economy"]["sell_rate"], None)

    def test_no_attempts_category_is_none_and_excluded(self):
        # only navigation + loop_health signal, no economy attempts
        recs = [rec(i, "farm", "success", dist=10.0 - i, kills=i) for i in range(5)]
        s = evaluation.evaluate(recs)
        self.assertIsNone(s["economy"]["sell_rate"])
        self.assertIsNone(s["economy"]["score"])
        self.assertNotIn("economy", s["categories_used"])

    def test_navigation_fraction(self):
        recs = [
            rec(0, "farm", "success", dist=10.0),
            rec(1, "farm", "success", dist=9.0),   # decreased
            rec(2, "farm", "success", dist=9.0),   # not decreased
        ]
        s = evaluation.evaluate(recs)
        self.assertAlmostEqual(s["navigation"]["dist_decrease_rate"], 0.5, places=6)

    def test_loop_health_max_repeat(self):
        recs = [rec(i, "turn_in_quest", "failure", dist=5.0) for i in range(7)]
        s = evaluation.evaluate(recs)
        self.assertEqual(s["loop_health"]["max_repeat_without_progress"], 7)
        self.assertAlmostEqual(s["loop_health"]["inconclusive_share"], 0.0, places=6)

    def test_format_report_is_string(self):
        text = evaluation.format_report(evaluation.evaluate(perfect_run()))
        self.assertIsInstance(text, str)
        self.assertIn("autonomy_score", text.lower())


class TestLoadRun(unittest.TestCase):
    def _write(self, lines):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_skips_malformed_lines(self):
        path = self._write([
            json.dumps({"step": 0, "pid": 7, "action": "farm", "verdict": "success"}),
            "=== step 0 autonomous summary (t=2s) ===",
            "  kills=885 quests_accepted=13",
            "",
            "{not json at all",
            json.dumps({"step": 1, "pid": 7, "action": "farm", "verdict": "failure"}),
        ])
        recs = evaluation.load_run(path)
        self.assertEqual(len(recs), 2)
        self.assertEqual([r["step"] for r in recs], [0, 1])

    def test_pid_none_returns_last_run_only(self):
        path = self._write([
            json.dumps({"step": 0, "pid": 100, "action": "farm", "verdict": "success"}),
            json.dumps({"step": 1, "pid": 100, "action": "farm", "verdict": "success"}),
            "=== summary ===",
            json.dumps({"step": 0, "pid": 5, "action": "buy", "verdict": "failure"}),
        ])
        recs = evaluation.load_run(path)
        self.assertEqual(len(recs), 1)
        self.assertTrue(all(r["pid"] == 5 for r in recs))

    def test_explicit_pid(self):
        path = self._write([
            json.dumps({"step": 0, "pid": 100, "action": "farm", "verdict": "success"}),
            json.dumps({"step": 0, "pid": 5, "action": "buy", "verdict": "failure"}),
        ])
        recs = evaluation.load_run(path, pid=100)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["pid"], 100)

    def test_missing_file_returns_empty(self):
        self.assertEqual(evaluation.load_run("no_such_file_xyz.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
