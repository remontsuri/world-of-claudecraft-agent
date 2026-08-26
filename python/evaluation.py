"""evaluation.py — Autonomy Benchmark (ARCHITECTURE.md §15).

Объективный AUTONOMY SCORE, чтобы сравнивать «было 61% -> стало 78%»,
а не «кажется, агент стал умнее».

Категория без попыток -> None и ИСКЛЮЧАЕТСЯ из среднего (не 0).

Запуск: cd python && python evaluation.py [путь] [--pid N]
"""
import json
import os
import sys
from typing import Any, Dict, List, Optional

DEFAULT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "autonomous_log.jsonl")

SUCCESS_VERDICTS = {"success", "SUCCESS"}
FAILURE_VERDICTS = {"failure", "FAILURE"}
INCONCLUSIVE_VERDICTS = {"inconclusive", "INCONCLUSIVE", "no_op", "NO_OP"}


# --------------------------------------------------------------------- load

def load_run(path: str = None, pid: Optional[int] = None) -> List[Dict[str, Any]]:
    """Прочитать autonomous_log.jsonl.

    Пропускает не-JSON строки (в файле есть сводки). pid=None -> вернуть
    ТОЛЬКО последний прогон (последняя группа pid по порядку появления),
    а не смесь всех запусков.
    """
    path = path or DEFAULT_LOG
    recs: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return recs
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict):
                recs.append(obj)
    if not recs:
        return recs
    if pid is not None:
        return [r for r in recs if r.get("pid") == pid]
    # последний прогон = pid последней записи, но берём непрерывный хвост
    last_pid = recs[-1].get("pid")
    out: List[Dict[str, Any]] = []
    for r in reversed(recs):
        if r.get("pid") != last_pid:
            break
        out.append(r)
    out.reverse()
    return out


# ------------------------------------------------------------------- helpers

def _rate(records: List[Dict[str, Any]], action: str) -> Optional[float]:
    """Доля успехов действия. None если попыток не было."""
    tries = [r for r in records if r.get("action") == action]
    if not tries:
        return None
    ok = sum(1 for r in tries if r.get("verdict") in SUCCESS_VERDICTS)
    return ok / len(tries)


def _attempts(records: List[Dict[str, Any]], action: str) -> int:
    return sum(1 for r in records if r.get("action") == action)


def _delta(records: List[Dict[str, Any]], field: str) -> float:
    vals = [r.get(field) for r in records if isinstance(r.get(field), (int, float))]
    if len(vals) < 2:
        return 0.0
    return float(vals[-1] - vals[0])


def _max_no_progress_run(records: List[Dict[str, Any]]) -> int:
    """Максимальная серия ОДНОГО действия без прогресса (меньше — лучше)."""
    best = cur = 0
    prev_action = None
    prev_key = None
    for r in records:
        act = r.get("action")
        key = (r.get("qprog"), r.get("kills"), r.get("xp"), r.get("deaths"))
        progressed = (prev_key is not None and key != prev_key)
        if act == prev_action and not progressed:
            cur += 1
        else:
            cur = 1
        best = max(best, cur)
        prev_action, prev_key = act, key
    return best


def _dist_improved_fraction(records: List[Dict[str, Any]]) -> Optional[float]:
    """Доля шагов, на которых дистанция до цели уменьшилась."""
    pairs = 0
    better = 0
    prev = None
    for r in records:
        d = r.get("dist")
        if not isinstance(d, (int, float)) or d >= 999:
            prev = None
            continue
        if prev is not None:
            pairs += 1
            if d < prev:
                better += 1
        prev = d
    if pairs == 0:
        return None
    return better / pairs


# ------------------------------------------------------------------ evaluate

def evaluate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Посчитать метрики и итоговый autonomy_score в 0..1."""
    n = len(records)
    if n == 0:
        return {
            "total_steps": 0, "autonomy_score": 0.0, "components": {},
            "quest": {}, "economy": {}, "combat": {}, "navigation": {},
            "loop_health": {}, "note": "no records",
        }

    accept = _rate(records, "accept_quest")
    turn_in = _rate(records, "turn_in_quest")
    qprog = _delta(records, "qprog")
    quests_done = _delta(records, "quests_done")

    sell = _rate(records, "sell_junk")
    buy = _rate(records, "buy")

    kills = _delta(records, "kills")
    deaths = _delta(records, "deaths")
    kills_per_100 = kills / n * 100.0
    deaths_per_100 = deaths / n * 100.0

    nav = _dist_improved_fraction(records)

    inconclusive = sum(1 for r in records
                       if r.get("verdict") in INCONCLUSIVE_VERDICTS)
    inconclusive_share = inconclusive / n
    max_run = _max_no_progress_run(records)

    # Нормировки в 0..1 (компоненты score)
    comp: Dict[str, Optional[float]] = {}
    comp["quest_accept"] = accept
    comp["quest_turn_in"] = turn_in
    comp["quest_progress"] = min(1.0, qprog / 8.0) if qprog > 0 else (0.0 if _attempts(records, "accept_quest") else None)
    comp["economy_sell"] = sell
    comp["economy_buy"] = buy
    # 1 килл на 10 шагов = 1.0
    comp["combat_kills"] = min(1.0, kills_per_100 / 10.0) if n >= 10 else None
    # Выживание считаем ТОЛЬКО если бой был: иначе «просто стоял и не умер»
    # получал бы 1.0 и вытягивал score у полностью бездействующего агента.
    if n >= 10 and (kills > 0 or deaths > 0):
        comp["combat_survival"] = max(0.0, 1.0 - deaths_per_100 / 5.0)
    else:
        comp["combat_survival"] = None
    comp["navigation"] = nav
    comp["loop_health"] = max(0.0, 1.0 - (max_run - 1) / 50.0)
    comp["effectiveness"] = 1.0 - inconclusive_share

    present = {k: v for k, v in comp.items() if v is not None}
    score = sum(present.values()) / len(present) if present else 0.0

    return {
        "total_steps": n,
        "pid": records[-1].get("pid"),
        "autonomy_score": round(score, 4),
        "components": {k: (round(v, 4) if v is not None else None)
                       for k, v in comp.items()},
        "quest": {
            "accept_attempts": _attempts(records, "accept_quest"),
            "accept_rate": accept,
            "turn_in_attempts": _attempts(records, "turn_in_quest"),
            "turn_in_rate": turn_in,
            "qprog_delta": qprog,
            "quests_done_delta": quests_done,
        },
        "economy": {
            "sell_attempts": _attempts(records, "sell_junk"),
            "sell_rate": sell,
            "buy_attempts": _attempts(records, "buy"),
            "buy_rate": buy,
        },
        "combat": {
            "kills_delta": kills,
            "kills_per_100": round(kills_per_100, 2),
            "deaths_delta": deaths,
            "deaths_per_100": round(deaths_per_100, 2),
        },
        "navigation": {"dist_improved_fraction": nav},
        "loop_health": {
            "max_no_progress_run": max_run,
            "inconclusive_share": round(inconclusive_share, 4),
        },
    }


# -------------------------------------------------------------------- report

def _fmt(v, pct=False):
    if v is None:
        return "n/a"
    if pct:
        return "%.1f%%" % (100.0 * v)
    if isinstance(v, float):
        return "%.2f" % v
    return str(v)


def format_report(score: Dict[str, Any]) -> str:
    L = []
    L.append("=" * 52)
    L.append(" AUTONOMY REPORT   steps=%s  pid=%s" % (
        score.get("total_steps"), score.get("pid")))
    L.append("=" * 52)
    L.append(" AUTONOMY SCORE: %s" % _fmt(score.get("autonomy_score"), pct=True))
    L.append("-" * 52)
    L.append(" component            value")
    for k, v in (score.get("components") or {}).items():
        L.append("  %-19s %s" % (k, _fmt(v, pct=True)))
    L.append("-" * 52)
    q = score.get("quest") or {}
    L.append(" QUEST     accept %s (%s tries)  turn_in %s (%s tries)" % (
        _fmt(q.get("accept_rate"), pct=True), q.get("accept_attempts"),
        _fmt(q.get("turn_in_rate"), pct=True), q.get("turn_in_attempts")))
    L.append("           qprog delta %s   quests_done delta %s" % (
        _fmt(q.get("qprog_delta")), _fmt(q.get("quests_done_delta"))))
    e = score.get("economy") or {}
    L.append(" ECONOMY   sell %s (%s)  buy %s (%s)" % (
        _fmt(e.get("sell_rate"), pct=True), e.get("sell_attempts"),
        _fmt(e.get("buy_rate"), pct=True), e.get("buy_attempts")))
    c = score.get("combat") or {}
    L.append(" COMBAT    kills %s (%s/100)  deaths %s (%s/100)" % (
        _fmt(c.get("kills_delta")), _fmt(c.get("kills_per_100")),
        _fmt(c.get("deaths_delta")), _fmt(c.get("deaths_per_100"))))
    nv = score.get("navigation") or {}
    L.append(" NAV       dist improved %s" % _fmt(nv.get("dist_improved_fraction"), pct=True))
    lh = score.get("loop_health") or {}
    L.append(" LOOP      max no-progress run %s   inconclusive %s" % (
        lh.get("max_no_progress_run"), _fmt(lh.get("inconclusive_share"), pct=True)))
    L.append("=" * 52)
    return "\n".join(L)


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    pid = None
    if "--pid" in argv:
        i = argv.index("--pid")
        try:
            pid = int(argv[i + 1])
        except (IndexError, ValueError):
            pid = None
        del argv[i:i + 2]
    path = argv[0] if argv else DEFAULT_LOG
    recs = load_run(path, pid=pid)
    print(format_report(evaluate(recs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
