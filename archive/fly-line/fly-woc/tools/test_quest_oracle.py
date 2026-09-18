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
     (204 — префикс 214; 224 не префикс 214, это ожидаемо);
  6) с --parity: быстрый путь выбора цели (first_target) сверяется с независимым
     эталоном на 4000 случайных наблюдений — переписывание на numpy не должно
     менять ни одного решения.

Запуск:
    python3 tools/test_quest_oracle.py
    python3 tools/test_quest_oracle.py data/quest_oracle_214.json --against data/quest_oracle.json
    python3 tools/test_quest_oracle.py --parity
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))          # quest_oracle.py, obs_layout.py лежат в корне линии
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



def _expected_first_quest(obs, table, layout):
    """Независимая (медленная) реализация выбора цели — эталон для --parity.

    Намеренно НЕ вызывает ни first_target(), ни guidance(): иначе тест проверял бы
    код сам себя. Логика выписана заново по протоколу оракула: идём по слотам в
    порядке таблицы, берём первый незакрытый с доступной целью, приоритет цели —
    «сдавать → брать → ближайшая незакрытая задача», дистанция и пеленг считаются
    из координат obs.
    """
    import numpy as np
    from quest_oracle import DIST_CLAMP, DIST_NORM, world_bounds
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    min_x, max_x, min_z, max_z = world_bounds(table)
    facing = float(np.arctan2(o[6], o[7]))
    x = float(o[4]) * max_x
    z = min_z + ((float(o[5]) + 1.0) * 0.5) * (max_z - min_z)
    for i in range(min(len(table["order"]), layout.n_quests)):
        base = layout.quest_base + 2 * i
        if base + 1 >= o.shape[0]:
            break
        st, prog = float(o[base]), float(o[base + 1])
        state = ("done" if st >= 0.99 else "ready" if st >= 0.5
                 else "active" if st > 0.01 else "untaken")
        if state == "done":
            continue
        q = table["quests"].get(table["order"][i]) or {}
        kind, target = None, None
        if state == "ready" and q.get("turnIn"):
            kind, target = "turn_in", q["turnIn"]
        elif state == "untaken" and q.get("giver"):
            kind, target = "accept", q["giver"]
        else:
            objs = q.get("objectives") or []
            if objs:
                idx = min(int(max(0.0, min(1.0, prog)) * len(objs)), len(objs) - 1)
                for j in list(range(idx, len(objs))) + list(range(0, idx)):
                    if objs[j].get("area"):
                        kind, target = f"objective[{j}:{objs[j]['type']}]", objs[j]["area"]
                        break
        if target is None:
            continue
        dx, dz = target["x"] - x, target["z"] - z
        dist = float(np.hypot(dx, dz))
        world = float(np.arctan2(dx, dz))
        rel = float(np.arctan2(np.sin(world - facing), np.cos(world - facing)))
        return {"quest": table["order"][i], "quest_state": state, "target_kind": kind,
                "dist_norm": round(min(dist / DIST_NORM, DIST_CLAMP), 3),
                "sin": round(float(np.sin(rel)), 3), "cos": round(float(np.cos(rel)), 3)}
    return {"quest": None}


def parity(n: int = 4000, seed: int = 7) -> int:
    """Сверка быстрого пути оракула с независимым эталоном на случайных наблюдениях.

    Зачем: first_target() отбирает незакрытые слоты одним numpy-сравнением вместо
    цикла по всем слотам. Это быстрее в 6.7x (137 мкс -> 20.5 мкс), но именно такие
    переписывания и теряют крайние случаи — «ready без turnIn», «objective без area»,
    «все закрыты». Проверяем на 4000 наблюдений, а не на одном.
    """
    import numpy as np
    from quest_oracle import load_table, guidance_from_obs, oracle_vector
    from obs_layout import configure

    table = load_table()
    layout = configure(obs_size=607, n_actions=61)
    rng = np.random.default_rng(seed)
    n_quests = len(table["order"])
    bad = 0
    kinds: dict[str, int] = {}
    for _ in range(n):
        o = rng.random(607, dtype=np.float32) * 0.4
        o[4] = rng.uniform(-1, 1); o[5] = rng.uniform(-1, 1)
        ang = rng.uniform(-3.14159, 3.14159)
        o[6], o[7] = np.sin(ang), np.cos(ang)
        base = 156                                    # блок квестов при obs=607
        states = rng.choice([0.0, 0.01, 0.33, 0.66, 1.0], size=n_quests,
                            p=[0.30, 0.05, 0.30, 0.20, 0.15])
        o[base:base + 2 * n_quests:2] = states
        o[base + 1:base + 2 * n_quests:2] = rng.random(n_quests).astype(np.float32)

        got = guidance_from_obs(o, table)
        exp = _expected_first_quest(o, table, layout)
        kinds[exp.get("target_kind") or "none"] = kinds.get(exp.get("target_kind") or "none", 0) + 1
        for key in ("quest", "quest_state", "target_kind", "dist_norm", "sin", "cos"):
            if key in exp and got.get(key) != exp[key]:
                bad += 1
                if bad <= 3:
                    print(f"  РАСХОЖДЕНИЕ {key}: быстрое={got.get(key)!r} эталон={exp[key]!r}")
                break
        vec = oracle_vector(o, table=table)
        if exp["quest"] is None:
            want = np.asarray([1.5, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        else:
            want = np.asarray([exp["dist_norm"], exp["sin"], exp["cos"],
                               1.0 if exp["quest_state"] == "active" else 0.0,
                               1.0 if exp["quest_state"] == "ready" else 0.0], dtype=np.float32)
        if not np.array_equal(vec, want):
            bad += 1
            if bad <= 6:
                print(f"  РАСХОЖДЕНИЕ oracle_vector: {vec} против {want}")
    print(f"  {'OK  ' if not bad else 'FAIL'} сверено {n} наблюдений, расхождений {bad}; "
          f"виды целей: {', '.join(f'{k}={v}' for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]))}")
    return 0 if not bad else 1


def main(argv: list[str]) -> int:
    args, against, i = [], None, 1
    while i < len(argv):
        if argv[i] == "--parity":
            print("быстрый путь оракула против независимого эталона")
            return parity()
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
