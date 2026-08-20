"""trend_analyze.py — offline cross-session trend aggregator (NO LLM, NO live loop).

Reads every autonomous_log*.jsonl in this directory, treats each file as one
agent session, computes the acceptance metrics per session, and reports the
delta between the two most recent sessions. This is the MISSING cross-session
piece: play_autonomous.py only tracks trends WITHIN a single run (via
_window_summary). Here we compare ACROSS runs so learning progress is visible
over time, not just inside one episode.

Output is plain text for a human (and later, safely, for an OFFLINE LLM advisor
that only READS this summary and proposes hypotheses — it never writes weights,
rewards, or experience files).

Usage:
    python trend_analyze.py            # all sessions, delta of last two
    python trend_analyze.py --top 5    # show N most recent sessions
"""
import glob
import json
import os
import sys
from collections import Counter, defaultdict


def _load_sessions(log_paths):
    sessions = []
    for path in log_paths:
        rows = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
        if rows:
            sessions.append((os.path.basename(path), rows))
    # sort by mtime so "last two" is chronological
    sessions.sort(key=lambda s: os.path.getmtime(
        os.path.join(os.path.dirname(__file__), s[0])))
    return sessions


def _metrics(rows):
    """Compute acceptance metrics from one session's rows (list of dicts)."""
    n = len(rows)
    if n == 0:
        return {}
    actions = Counter(r.get("action") for r in rows)
    quests_turned_in = sum(
        1 for r in rows if r.get("action") == "turn_in_quest" and r.get("verdict") == "SUCCESS")
    quest_turnin_fail = sum(
        1 for r in rows if r.get("action") in ("turn_in_quest", "return_to_giver")
        and r.get("verdict") in ("FAILURE", "INCONCLUSIVE"))
    giver_hits = sum(1 for r in rows if r.get("action") in ("return_to_giver", "turn_in_quest"))
    # navigation stuck: return_to_giver PARTIAL or turn_in INCONCLUSIVE
    nav_stuck = sum(1 for r in rows if r.get("action") == "return_to_giver"
                    and r.get("verdict") == "PARTIAL") + \
                sum(1 for r in rows if r.get("action") == "turn_in_quest"
                    and r.get("verdict") == "INCONCLUSIVE")
    quest_completed = sum(1 for r in rows if r.get("quest_status") == "READY_TO_TURN_IN")
    reward_sum = sum((r.get("reward") or 0) for r in rows)
    deaths = rows[-1].get("deaths", 0)
    kills = rows[-1].get("kills", 0)
    turns = quests_turned_in
    attempts = turns + quest_turnin_fail
    qtr = (turns / attempts) if attempts else 0.0
    return {
        "steps": n,
        "quests_turned_in": turns,
        "quests_completed": quest_completed,
        "quest_turnin_rate": round(qtr, 3),
        "quest_turnin_failures": quest_turnin_fail,
        "giver_memory_events": giver_hits,
        "navigation_stuck": nav_stuck,
        "deaths": deaths,
        "kills": kills,
        "reward_mean": round(reward_sum / n, 4),
        "action_dist": dict(actions.most_common(8)),
    }


def _delta(a, b):
    """b is newer session, a is previous. Returns dict of deltas for shared keys."""
    out = {}
    for k in a:
        if k in b and isinstance(a[k], (int, float)) and k not in ("action_dist",):
            out[k] = b[k] - a[k]
    return out


def main():
    top = 2
    if "--top" in sys.argv:
        try:
            top = int(sys.argv[sys.argv.index("--top") + 1])
        except (ValueError, IndexError):
            top = 2
    here = os.path.dirname(os.path.abspath(__file__))
    paths = sorted(glob.glob(os.path.join(here, "autonomous_log*.jsonl")))
    if not paths:
        print("no autonomous_log*.jsonl found")
        return
    sessions = _load_sessions(paths)
    if not sessions:
        print("no parseable sessions")
        return

    print(f"=== cross-session trend ({len(sessions)} sessions found) ===\n")
    recent = sessions[-top:]
    for name, rows in recent:
        m = _metrics(rows)
        print(f"--- {name}  ({m.get('steps', 0)} steps) ---")
        for k, v in m.items():
            if k == "action_dist":
                print(f"  {k}: {v}")
            else:
                print(f"  {k}: {v}")
        print()

    if len(recent) >= 2:
        prev_m = _metrics(recent[-2][1])
        new_m = _metrics(recent[-1][1])
        d = _delta(prev_m, new_m)
        print("=== DELTA (newest - previous) ===")
        for k, v in d.items():
            arrow = "▲" if v > 0 else ("▼" if v < 0 else " ")
            print(f"  {k}: {v:+}  {arrow}")
        # headline interpretation hints (facts, not opinions)
        if d.get("quest_turnin_rate", 0) > 0:
            print("\n  ✅ quest_turnin_rate improving across sessions")
        elif d.get("quest_turnin_rate", 0) < 0:
            print("\n  ⚠ quest_turnin_rate regressed across sessions")
        if d.get("navigation_stuck", 0) < 0:
            print("  ✅ navigation_stuck decreasing (agent gets unstuck more)")


if __name__ == "__main__":
    main()
