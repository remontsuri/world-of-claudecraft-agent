#!/usr/bin/env python3
"""quest_oracle.py — куда идти по квесту, не заглядывая в Sim.

В obs игры 224 квеста лежат парами (state, progress), порядок — `QUEST_ORDER` из
`src/sim/data.ts`, он же порядок, в котором их пишет `src/sim/obs.ts`.
Статическая таблица `data/quest_oracle.json` получается из самого игрового
резолвера `src/sim/quest_targets.ts` (см. `tools/dump_quest_oracle.ts`) и
содержит для каждого квеста координаты выдающего/принимающего NPC и зоны каждой
цели.

Начало квестового блока (бывший QUEST_BASE = 156) НЕ захардкожено: игра считает
размер obs как 63 + 2*ABILITY_SLOTS + 2*КВЕСТЫ, и при смене числа слотов
способностей (48 → 28 в текущей версии, obs 607 → 567) все индексы после
способностей сдвигаются. Раскладка выводится из длины obs и числа квестов —
см. `obs_layout.py`.

Почему это нужно: без координат цели агент узнаёт о квесте только тогда, когда
случайно подойдёт к нужному мобу — 224 квеста так не перебрать (в замерах
политика закрывает 1 квест и застревает). Оракул превращает квестовый цикл из
exploration в навигацию.

Конвенции obs (src/sim/obs.ts): x → obs[4], z → obs[5]; расстояния уже d/40 с
обрезкой 1.5; пеленг передаём как (sin, cos) относительного угла.

Запуск:
    python3 quest_oracle.py --check          # сверка с живым симом
    python3 quest_oracle.py --table          # сводка таблицы
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))  # obs_layout рядом
from obs_layout import ObsLayout, from_obs, quest_count  # noqa: E402

N_QUESTS = quest_count()  # QUEST_ORDER.length: из data/quest_oracle.json, не константа
WORLD_MAX_X = 900.0       # src/sim/data.ts: WORLD_MAX_X
DIST_NORM = 40.0          # obs хранит d/40 ...
DIST_CLAMP = 1.5          # ... с обрезкой 1.5

TABLE_PATH = Path(__file__).parent / "data" / "quest_oracle.json"


def load_table(path: Path | None = None) -> dict:
    return json.loads(Path(path or os.environ.get("WOC_QUEST_TABLE") or TABLE_PATH).read_text())


def table_path_for_game() -> Path:
    return Path(os.environ.get("WOC_QUEST_TABLE") or TABLE_PATH)


def decode_state(v: float) -> str:
    """obs хранит 1/0.66/0.33/0 — обратно в слова (obs.ts)."""
    if v >= 0.99:
        return "done"
    if v >= 0.5:
        return "ready"
    if v > 0.01:
        return "active"
    return "untaken"


def quest_slots(obs: np.ndarray, table: dict, layout: ObsLayout | None = None,
                n_actions: int | None = None) -> list[tuple[str, str, float]]:
    """[(questId, state, progress)] для всех слотов квестов в obs.

    Раскладка берётся из длины obs (obs_layout), а не из константы: игра меняет
    число слотов способностей, и блок квестов вместе с ними сдвигается.
    """
    obs = np.asarray(obs, dtype=np.float32).reshape(-1)
    layout = layout or from_obs(obs, n_actions=n_actions)
    out = []
    for i, qid in enumerate(table["order"]):
        base = layout.quest_base + 2 * i
        state = decode_state(float(obs[base]))
        prog = float(obs[base + 1])
        out.append((qid, state, prog))
    return out


def _target_for(quest: dict, prog: float, state: str) -> tuple[str, dict | None]:
    """Куда идти: сдавать / добивать цель / брать у NPC."""
    if state == "ready" and quest.get("turnIn"):
        return "turn_in", quest["turnIn"]
    if state == "untaken" and quest.get("giver"):
        return "accept", quest["giver"]
    objs = quest.get("objectives") or []
    if not objs:
        return "no_objectives", None
    idx = min(int(max(0.0, min(1.0, prog)) * len(objs)), len(objs) - 1)
    for j in list(range(idx, len(objs))) + list(range(0, idx)):
        area = objs[j].get("area")
        if area:
            return f"objective[{j}:{objs[j]['type']}]", area
    return "no_coords", None


def guidance(obs: np.ndarray, x: float, z: float, facing: float, table: dict | None = None,
             layout: ObsLayout | None = None) -> dict:
    """Первый по порядку незакрытый квест → куда идти и сколько осталось пути.

    x, z — мировые координаты (obs[4] * WORLD_MAX_X), facing — радианы.
    """
    table = table or load_table()
    slots = quest_slots(obs, table, layout=layout)
    for qid, state, prog in slots:
        if state == "done":
            continue
        quest = table["quests"].get(qid) or {}
        kind, target = _target_for(quest, prog, state)
        if target is None:
            continue
        dx, dz = target["x"] - x, target["z"] - z
        dist = float(np.hypot(dx, dz))
        world_angle = float(np.arctan2(dz, dx))
        rel = float(np.arctan2(np.sin(world_angle - facing), np.cos(world_angle - facing)))
        return {
            "quest": qid, "name": quest.get("name"), "quest_state": state,
            "quest_progress": round(prog, 3), "target_kind": kind,
            "target": {"x": round(target["x"], 1), "z": round(target["z"], 1)},
            "dist": round(dist, 1), "dist_norm": round(min(dist / DIST_NORM, DIST_CLAMP), 3),
            "bearing_rel": round(rel, 3),
            "sin": round(float(np.sin(rel)), 3), "cos": round(float(np.cos(rel)), 3),
        }
    return {"quest": None, "name": None, "target_kind": "all_done"}


def guidance_from_obs(obs: np.ndarray, table: dict | None = None,
                      n_actions: int | None = None) -> dict:
    """Самодостаточно: x, z и facing берём из obs (4, 5, 6/7 — obs.ts)."""
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    facing = float(np.arctan2(o[6], o[7]))
    return guidance(o, float(o[4]) * WORLD_MAX_X, float(o[5]) * WORLD_MAX_X, facing, table,
                    layout=from_obs(o, n_actions=n_actions))


def oracle_vector(obs: np.ndarray, x: float | None = None, z: float | None = None,
                  facing: float | None = None, table: dict | None = None,
                  layout: ObsLayout | None = None, n_actions: int | None = None) -> np.ndarray:
    """5 чисел для бокового канала политики: [dist_norm, sin, cos, active?, ready?].

    Оба аргумента (layout / n_actions) нужны только для сверки раскладки; сам
    вектор всегда начинается с блока квестов, выведенного из длины obs.

    Если координаты не переданы, берём их из самой obs. Когда незакрытых квестов
    нет — dist_norm = 1.5 (максимум), чтобы «нечего делать» не читалось как
    «стоим на цели».
    """
    g = (guidance_from_obs(obs, table, n_actions=n_actions) if x is None
         else guidance(obs, x, z, facing or 0.0, table, layout=layout))
    if g.get("quest") is None:
        return np.asarray([DIST_CLAMP, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    state = g["quest_state"]
    return np.asarray([g["dist_norm"], g["sin"], g["cos"],
                       1.0 if state == "active" else 0.0,
                       1.0 if state == "ready" else 0.0], dtype=np.float32)


def check(steps: int = 60, seed: int = 900001) -> int:
    """Живой сим: сверяем слоты obs и координаты оракула на первых шагах."""
    sys.path.insert(0, os.environ.get("WOC_PYTHON_PATH", "/home/user/woc-game/python"))
    from wow_env import WoWClassicEnv  # noqa: E402

    table = load_table()
    env = WoWClassicEnv(player_class="warrior", max_steps=steps)
    obs, info = env.reset(seed=seed)
    # Раскладку сверяем по ДВУМ величинам окружения: длина obs и число действий.
    from obs_layout import configure
    try:
        layout = configure(obs_size=int(np.asarray(obs).shape[0]), n_actions=int(env.action_space.n))
    except ValueError as exc:
        game = table.get("game") or {}
        print("ТАБЛИЦА НЕ ОТ ЭТОЙ СБОРКИ ИГРЫ")
        print(f"  {exc}")
        print(f"  в таблице {table.get('game', {}).get('quests_count', len(table['order']))} квестов "
              f"(файл снят с obs={game.get('obs_size', '?')}, действий={game.get('actions', '?')})")
        print("  что делать: перегенерировать таблицу под свою версию игры —")
        print("    npx esbuild tools/dump_quest_oracle.ts --bundle --platform=node \\")
        print("        --format=cjs --outfile=/tmp/dump.cjs && node /tmp/dump.cjs > data/quest_oracle.json")
        print("  либо указать готовую таблицу: WOC_QUEST_TABLE=data/quest_oracle_204.json")
        env.close()
        return 2
    if layout.n_quests != len(table["order"]):
        print(f"ВНИМАНИЕ: в таблице {len(table['order'])} квестов, окружение говорит про "
              f"{layout.n_quests} — канал и шейпинг работать не будут.")
        env.close()
        return 2
    print(f"obs={np.asarray(obs).shape[0]}  слотов квестов: {layout.n_quests}  "
          f"(в таблице {len(table['order'])})")
    print(f"раскладка: {layout.describe()}")
    seen_states, rows = set(), []
    for t in range(steps):
        a = env.action_space.sample()
        obs, r, term, trunc, info = env.step(int(a))
        slots = quest_slots(obs, table, layout=layout)
        seen_states.update(s for _, s, _ in slots)
        g = guidance(obs, float(obs[4]) * WORLD_MAX_X, float(obs[5]) * WORLD_MAX_X, 0.0, table,
                     layout=layout)
        rows.append((t, g.get("quest"), g.get("quest_state"), g.get("target_kind"),
                     g.get("dist"), g.get("target")))
        if term or trunc:
            break
    env.close()
    print("состояния в слотах obs:", sorted(seen_states))
    print(f"{'t':>4} {'quest':<22} {'state':<7} {'target':<20} {'dist':>8}  coords")
    for t, q, st, kind, dist, tgt in rows[:6] + rows[-4:]:
        print(f"{t:>4} {str(q):<22} {str(st):<7} {str(kind):<20} {str(dist):>8}  {tgt}")
    bad = seen_states - {"untaken", "active", "ready", "done"}
    print("вердикт:", "OK — слоты и координаты читаются" if not bad else f"ПОДОЗРИТЕЛЬНО: {bad}")
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="сверка с живым симом")
    ap.add_argument("--steps", type=int, default=60, help="шагов для --check")
    ap.add_argument("--table", action="store_true", help="сводка таблицы")
    args = ap.parse_args()
    if args.check:
        return check(args.steps)
    if args.table:
        table = load_table()
        q = table["quests"]
        with_area = sum(1 for v in q.values() for o in v["objectives"] if o["area"])
        total = sum(len(v["objectives"]) for v in q.values())
        chained = sum(1 for v in q.values() if v["requires"])
        print(f"квестов: {len(q)} | порядок obs совпадает: {len(table['order']) == N_QUESTS}")
        print(f"целей с координатами: {with_area}/{total} | в цепочках requires: {chained}")
        for qid in table["order"][:5]:
            v = q[qid]
            print(f"  {qid:<24} {v['name']:<34} xp={v['xp']:<4} целей={len(v['objectives'])}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
