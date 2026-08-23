"""Fix1 regression: the per-step jsonl row must carry the FSM phase.

2026-08-23 post-mortem: 848-step run pinned in return/turn_in, but the log had
no `goal` field, so the pocket trajectory was invisible and the diagnosis took
a manual code dig. Every future autopsy must read the phase straight from the
row.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def test_log_row_includes_goal():
    src = open(os.path.join(os.path.dirname(__file__), "play_autonomous.py"),
               encoding="utf-8").read()
    # locate the row dict that is dumped to autonomous_log.jsonl
    i = src.find("json.dumps(row")
    assert i != -1, "log row dump not found"
    seg = src[max(0, i - 900):i]
    assert '"goal"' in seg or "'goal'" in seg, (
        "row dict does not log goal_fsm.goal — FSM phase invisible in jsonl")
    # it must come from the live FSM object, not a stale constant
    m = [line for line in seg.splitlines() if "goal" in line
         and ("#" not in line.split("goal")[0] or True)]
    assert any("fsm" in line.lower() for line in m), (
        f"goal field not wired to fsm: {m}")
