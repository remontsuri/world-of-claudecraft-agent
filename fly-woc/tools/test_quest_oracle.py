#!/usr/bin/env python3
"""test_quest_oracle.py — приёмка таблиц оракула без игры, GPU и сети.

Что проверяется у каждой data/quest_oracle*.json:
  1) схема: game/order/quests; ключи game и квестов — как у соседних таблиц;
  2) арифметика сборки: quests_count == (obs_size - 63 - 2*ability_slots) / 2,
     base_actions + ability_slots == actions, len(order) == len(quests) == quests_count;
  3) world_bounds на месте: с ними quest_oracle.py нормализует x/z как obs.ts, без
     них молча берёт свои дефолты (у v0.40.0 maxZ=2420, у v0.42.2 maxZ=2380 —
     границы уже разъезжались);
  4) данные: у каждого квеста giver и turnIn с координатами, ≥80 % целей с area,
     id в order уникальны, requires ссылается только на свои же квесты;
  5) с --against: префиксность порядка — диагностика совместимости сборок
     (204 — префикс 214; 224 не префикс 214, это ожидаемо).

Запуск:
    python3 tools/test_quest_oracle.py
    python3 tools/test_quest_oracle.py data/quest_oracle_214.json --against data/quest_oracle.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
GAME_KEYS = {"quests_count", "obs_size", "actions", "ability_slots", "base_actions", "world_bounds"}
QUEST_KEYS = {"name", "giver", "turnIn", "requires", "xp", "copper", "objectives"}
OBJ_KEYS = {"type", "count", "targetMobId", "itemId", "targetNpcId", "campId", "area"}
MIN_AREA_SHARE = 0.80


def check(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        t = json.loads(path.read_text())
    except Exception as exc:                                   # noqa: BLE001
        return [f"не читается: {exc}"]

    for key in ("game", "order", "quests"):
        if key not in t:
            issues.append(f"нет ключа {key}")
    if issues:
        return issues

    g, order, quests = t["game"], t["order"], t["quests"]
    missing = GAME_KEYS - set(g)
    if missing:
        issues.append(f"game: нет {sorted(missing)}")
    if g.get("base_actions", 0) + g.get("ability_slots", 0) != g.get("actions"):
        issues.append("base_actions + ability_slots != actions")
    n_expect = (g["obs_size"] - 63 - 2 * g["ability_slots"]) / 2
    if n_expect != g["quests_count"]:
        issues.append(f"obs={g['obs_size']} не согласуется с {g['quests_count']} квестами (ожидалось {n_expect:g})")
    if not (len(order) == len(quests) == g["quests_count"]):
        issues.append(f"order={len(order)} quests={len(quests)} quests_count={g['quests_count']}")
    if len(set(order)) != len(order):
        issues.append("в order есть дубликаты id")
    wb = g.get("world_bounds") or {}
    if {"minX", "maxX", "minZ", "maxZ"} - set(wb):
        issues.append("world_bounds отсутствует или неполон")

    no_giver = no_turnin = no_obj = 0
    obj_total = obj_area = 0
    bad_requires = 0
    for qid in order:
        q = quests.get(qid)
        if q is None:
            issues.append(f"id {qid} из order нет в quests")
            continue
        miss = QUEST_KEYS - set(q)
        if miss:
            issues.append(f"{qid}: нет {sorted(miss)}")
        for slot in ("giver", "turnIn"):
            pos = q.get(slot) or {}
            if not isinstance(pos.get("x"), (int, float)) or not isinstance(pos.get("z"), (int, float)):
                no_giver += slot == "giver"
                no_turnin += slot == "turnIn"
        objs = q.get("objectives") or []
        no_obj += not objs
        for o in objs:
            obj_total += 1
            extra = set(o) - OBJ_KEYS
            if extra:
                issues.append(f"{qid}: лишние поля цели {sorted(extra)}")
            area = o.get("area") or {}
            obj_area += isinstance(area.get("x"), (int, float)) and isinstance(area.get("z"), (int, float))
        req = q.get("requires")
        if req and req not in quests:
            bad_requires += 1
    if no_giver:
        issues.append(f"без координат выдающего: {no_giver}")
    if no_turnin:
        issues.append(f"без координат принимающего: {no_turnin}")
    if no_obj:
        issues.append(f"без целей: {no_obj}")
    if obj_total and obj_area / obj_total < MIN_AREA_SHARE:
        issues.append(f"координатами покрыто {obj_area}/{obj_total} целей (< {MIN_AREA_SHARE:.0%})")
    if bad_requires:
        issues.append(f"requires ссылается на квест вне таблицы: {bad_requires}")
    return issues


def prefix_len(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def main(argv: list[str]) -> int:
    args, against, i = [], None, 1
    while i < len(argv):
        if argv[i] == "--against":
            against = Path(argv[i + 1]); i += 2; continue
        args.append(argv[i]); i += 1
    files = [Path(a) for a in args[1:]] or sorted((HERE / "data").glob("quest_oracle*.json"))
    if not files:
        print("нет таблиц: ожидались data/quest_oracle*.json")
        return 1

    ok = True
    print("таблицы оракула")
    for f in files:
        issues = check(f)
        ok &= not issues
        try:
            g = json.loads(f.read_text())["game"]
            info = f"{g['quests_count']} квестов, obs={g['obs_size']}, actions={g['actions']}"
        except Exception:                                      # noqa: BLE001
            info = "?"
        print(f"  {'OK  ' if not issues else 'FAIL'} {f.name:26s} {info}")
        for i in issues:
            print(f"        - {i}")

    if against is not None:
        print(f"\nсовместимость порядка (диагностика): {against.name} vs остальные")
        ref = json.loads(against.read_text())["order"]
        for f in files:
            if f == against:
                continue
            other = json.loads(f.read_text())["order"]
            n = prefix_len(ref, other)
            verdict = "префикс — короткий список безопасен" if n == min(len(ref), len(other)) else "порядок расходится"
            print(f"  {f.name:26s} общих первых позиций={n:4d}/{min(len(ref), len(other)):4d} — {verdict}")

    print("\nитог:", "все таблицы прошли проверку" if ok else "есть провалы")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
