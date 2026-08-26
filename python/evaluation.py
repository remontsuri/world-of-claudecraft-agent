"""Autonomy Evaluation Suite (ARCHITECTURE.md section 15, Task 10).

Turns an autonomous_log.jsonl run into an objective AUTONOMY SCORE in 0..1 so
code changes can be compared as "before 61% -> after 78%".

Usage:
    python -m evaluation                 # latest run in ./autonomous_log.jsonl
    python -m evaluation <path> [pid]
"""
from __future__ import annotations

import json
import os
import sys

DEFAULT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "autonomous_log.jsonl")

# Normalisation thresholds: value at/above which the sub-metric scores 1.0
KILLS_PER_100_TARGET = 5.0
DEATHS_PER_100_TOLERANCE = 5.0
LOOP_TOLERANCE = 10.0  # a stuck-run of 1+LOOP_TOLERANCE repeats scores 0

COMBAT_ACTIONS = {"farm", "cast_fireball", "cast_frostbolt", "loot", "heal", "gather"}


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def load_run(path: str = DEFAULT_LOG, pid=None) -> list:
    """Parse autonomous_log.jsonl, skipping non-JSON summary lines.

    When ``pid`` is None the LAST run is selected (the pid whose first
    appearance is latest in the file), so runs are never mixed.
    """
    if not path or not os.path.isfile(path):
        return []
    records = []
    order = []
    seen = set()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(rec, dict):
                continue
            records.append(rec)
            p = rec.get("pid")
            if p not in seen:
                seen.add(p)
                order.append(p)
    if not records:
        return []
    target = order[-1] if pid is None else pid
    return [r for r in records if r.get("pid") == target]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _verdict(rec) -> str:
    v = rec.get("verdict")
    return str(v).strip().lower() if v is not None else ""


def _rate(success: int, attempts: int):
    """Success rate, or None when there were no attempts (never divides by 0)."""
    if not attempts:
        return None
    return success / float(attempts)


def _num(rec, key):
    v = rec.get(key)
    if isinstance(v, bool):
        return None
    return v if isinstance(v, (int, float)) else None


def _mean(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / float(len(vals))


def _clamp(x):
    return max(0.0, min(1.0, x))


def _action_rate(records, action):
    attempts = 0
    ok = 0
    for r in records:
        if r.get("action") == action:
            attempts += 1
            if _verdict(r) == "success":
                ok += 1
    return _rate(ok, attempts), attempts


def _delta(records, key):
    vals = [_num(r, key) for r in records]
    vals = [v for v in vals if v is not None]
    if len(vals) < 1:
        return None
    return vals[-1] - vals[0]


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
def _made_progress(prev, cur) -> bool:
    """Did this step produce any observable progress?"""
    if _verdict(cur) == "success":
        return True
    if prev is None:
        return False
    for key in ("qprog", "kills", "xp"):
        a, b = _num(prev, key), _num(cur, key)
        if a is not None and b is not None and b > a:
            return True
    a, b = _num(prev, "dist"), _num(cur, "dist")
    if a is not None and b is not None and b < a:
        return True
    return False


def evaluate(records: list) -> dict:
    records = list(records or [])
    steps = len(records)

    # ---- quest ----------------------------------------------------------- #
    accept_rate, accept_n = _action_rate(records, "accept_quest")
    turn_in_rate, turn_in_n = _action_rate(records, "turn_in_quest")
    qprog_delta = _delta(records, "qprog")
    qprog_metric = None
    if qprog_delta is not None and (accept_n or turn_in_n or steps):
        qprog_metric = 1.0 if qprog_delta > 0 else 0.0
    quest_parts = [accept_rate, turn_in_rate]
    if accept_n or turn_in_n:
        quest_parts.append(qprog_metric)
    quest_score = _mean(quest_parts)
    quest = {
        "accept_rate": accept_rate,
        "accept_attempts": accept_n,
        "turn_in_rate": turn_in_rate,
        "turn_in_attempts": turn_in_n,
        "qprog_delta": qprog_delta,
        "score": quest_score,
    }

    # ---- economy --------------------------------------------------------- #
    sell_rate, sell_n = _action_rate(records, "sell_junk")
    buy_rate, buy_n = _action_rate(records, "buy")
    economy = {
        "sell_rate": sell_rate,
        "sell_attempts": sell_n,
        "buy_rate": buy_rate,
        "buy_attempts": buy_n,
        "score": _mean([sell_rate, buy_rate]),
    }

    # ---- combat ---------------------------------------------------------- #
    kills_delta = _delta(records, "kills")
    deaths_delta = _delta(records, "deaths")
    combat_actions = sum(1 for r in records if r.get("action") in COMBAT_ACTIONS)
    has_combat = bool(combat_actions) or bool(kills_delta) or bool(deaths_delta)
    kills_per_100 = deaths_per_100 = None
    combat_score = None
    if steps and has_combat:
        if kills_delta is not None:
            kills_per_100 = 100.0 * max(0.0, float(kills_delta)) / steps
        if deaths_delta is not None:
            deaths_per_100 = 100.0 * max(0.0, float(deaths_delta)) / steps
        kill_metric = (None if kills_per_100 is None
                       else _clamp(kills_per_100 / KILLS_PER_100_TARGET))
        death_metric = (None if deaths_per_100 is None
                        else _clamp(1.0 - deaths_per_100 / DEATHS_PER_100_TOLERANCE))
        combat_score = _mean([kill_metric, death_metric])
    combat = {
        "kills_per_100_steps": kills_per_100,
        "deaths_per_100_steps": deaths_per_100,
        "combat_actions": combat_actions,
        "score": combat_score,
    }

    # ---- navigation ------------------------------------------------------ #
    pairs = 0
    decreased = 0
    prev_dist = None
    for r in records:
        d = _num(r, "dist")
        if d is not None and prev_dist is not None:
            pairs += 1
            if d < prev_dist:
                decreased += 1
        if d is not None:
            prev_dist = d
    nav_rate = _rate(decreased, pairs)
    navigation = {
        "dist_decrease_rate": nav_rate,
        "dist_samples": pairs,
        "score": nav_rate,
    }

    # ---- loop health ----------------------------------------------------- #
    max_run = 0
    cur_run = 0
    cur_action = object()
    prev = None
    for r in records:
        act = r.get("action")
        progressed = _made_progress(prev, r)
        if progressed:
            cur_run = 0
            cur_action = object()
        else:
            if act == cur_action:
                cur_run += 1
            else:
                cur_action = act
                cur_run = 1
            if cur_run > max_run:
                max_run = cur_run
        prev = r
    inconclusive = sum(1 for r in records if _verdict(r) == "inconclusive")
    inconclusive_share = _rate(inconclusive, steps)
    if steps:
        loop_metric = _clamp(1.0 - max(0, max_run - 1) / LOOP_TOLERANCE)
        inc_metric = _clamp(1.0 - (inconclusive_share or 0.0))
        loop_score = _mean([loop_metric, inc_metric])
    else:
        loop_score = None
    loop_health = {
        "max_repeat_without_progress": max_run if steps else None,
        "inconclusive_share": inconclusive_share,
        "score": loop_score,
    }

    cats = {
        "quest": quest,
        "economy": economy,
        "combat": combat,
        "navigation": navigation,
        "loop_health": loop_health,
    }
    used = [name for name in ("quest", "economy", "combat", "navigation", "loop_health")
            if cats[name]["score"] is not None]
    overall = _mean([cats[n]["score"] for n in used])

    out = dict(cats)
    out["steps"] = steps
    out["pid"] = records[0].get("pid") if records else None
    out["categories_used"] = used
    out["autonomy_score"] = 0.0 if overall is None else _clamp(overall)
    return out


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def _fmt(v, spec="{:.3f}"):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return spec.format(v)
    return str(v)


def format_report(score: dict) -> str:
    s = score or {}
    lines = []
    lines.append("=" * 58)
    lines.append("WoC AGENT AUTONOMY REPORT")
    lines.append("=" * 58)
    lines.append("run pid : {}".format(_fmt(s.get("pid"))))
    lines.append("steps   : {}".format(_fmt(s.get("steps"))))
    lines.append("-" * 58)
    lines.append("{:<32}{:>10}{:>14}".format("METRIC", "VALUE", "CATEGORY"))
    lines.append("-" * 58)

    rows = [
        ("quest", [("accept success rate", "accept_rate", "{:.3f}"),
                   ("accept attempts", "accept_attempts", None),
                   ("turn_in success rate", "turn_in_rate", "{:.3f}"),
                   ("turn_in attempts", "turn_in_attempts", None),
                   ("qprog delta", "qprog_delta", None)]),
        ("economy", [("sell_junk success rate", "sell_rate", "{:.3f}"),
                     ("sell attempts", "sell_attempts", None),
                     ("buy success rate", "buy_rate", "{:.3f}"),
                     ("buy attempts", "buy_attempts", None)]),
        ("combat", [("kills / 100 steps", "kills_per_100_steps", "{:.2f}"),
                    ("deaths / 100 steps", "deaths_per_100_steps", "{:.2f}"),
                    ("combat actions", "combat_actions", None)]),
        ("navigation", [("dist decreased fraction", "dist_decrease_rate", "{:.3f}"),
                        ("dist samples", "dist_samples", None)]),
        ("loop_health", [("max repeat w/o progress", "max_repeat_without_progress", None),
                         ("inconclusive share", "inconclusive_share", "{:.3f}")]),
    ]
    for cat, metrics in rows:
        block = s.get(cat) or {}
        lines.append("[{}]".format(cat))
        for label, key, spec in metrics:
            val = _fmt(block.get(key), spec or "{:.3f}")
            lines.append("{:<32}{:>10}".format("  " + label, val))
        lines.append("{:<32}{:>10}{:>14}".format("  category score", _fmt(block.get("score")),
                                                 "used" if block.get("score") is not None
                                                 else "excluded"))
    lines.append("-" * 58)
    lines.append("categories used: {}".format(", ".join(s.get("categories_used") or []) or "none"))
    a = s.get("autonomy_score", 0.0) or 0.0
    lines.append("AUTONOMY_SCORE : {:.4f}  ({:.1f}%)".format(a, a * 100.0))
    lines.append("=" * 58)
    return "\n".join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else DEFAULT_LOG
    pid = int(argv[1]) if len(argv) > 1 else None
    records = load_run(path, pid=pid)
    if not records:
        print("no records found in {}".format(path))
        return 1
    print(format_report(evaluate(records)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
