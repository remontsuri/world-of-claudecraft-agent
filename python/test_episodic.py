import os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from episodic import EpisodicLog

def test_append_and_recent_by_quest():
    td = tempfile.mkdtemp()
    log = EpisodicLog(path=os.path.join(td, "e.jsonl"))
    log.append({"t": 1, "quest": "q_a", "step": 1, "action": "accept_quest",
                "result": "FAILURE", "reason": "already_active", "hp_frac": 0.9,
                "phase": "NO_QUEST"})
    log.append({"t": 2, "quest": "q_b", "step": 2, "action": "farm",
                "result": "SUCCESS", "hp_frac": 0.9})
    assert [r["quest"] for r in log.recent("q_a", n=5)] == ["q_a"]
    assert len(log.recent(None, n=10)) == 2

def test_recent_failures_only_failures():
    td = tempfile.mkdtemp()
    log = EpisodicLog(path=os.path.join(td, "e.jsonl"))
    for i, res in enumerate(["SUCCESS", "FAILURE", "SUCCESS", "FAILURE"]):
        log.append({"t": i, "quest": f"q{i}", "step": i, "action": "x",
                    "result": res, "hp_frac": 0.9})
    fails = log.recent_failures(n=3)
    assert len(fails) == 2 and all(f["result"] == "FAILURE" for f in fails)

def test_missing_fields_tolerated():
    td = tempfile.mkdtemp()
    log = EpisodicLog(path=os.path.join(td, "e.jsonl"))
    log.append({"t": 1, "action": "loot"})          # почти пусто
    r = log.recent(n=1)[0]
    assert r["result"] is None and r["quest"] is None

def test_corrupt_lines_skipped():
    td = tempfile.mkdtemp()
    p = os.path.join(td, "e.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"t":1,"quest":"q_x","action":"a"}\nNOT JSON AT ALL\n')
    log = EpisodicLog(path=p)
    assert len(log.recent(n=10)) == 1
