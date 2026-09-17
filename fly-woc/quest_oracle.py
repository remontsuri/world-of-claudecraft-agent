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
WORLD_MIN_X = -540.0      # current main: min zone x bound
WORLD_MAX_X = 540.0       # current main: max zone x bound
WORLD_MIN_Z = -180.0      # current main: min zone z bound
WORLD_MAX_Z = 2380.0      # current main: max zone z bound
DIST_NORM = 40.0          # obs хранит d/40 ...
DIST_CLAMP = 1.5          # ... с обрезкой 1.5

TABLE_PATH = Path(__file__).parent / "data" / "quest_oracle.json"


def load_table(path: Path | None = None) -> dict:
    return json.loads(Path(path or os.environ.get("WOC_QUEST_TABLE") or TABLE_PATH).read_text())



def world_bounds(table: dict | None = None) -> tuple[float, float, float, float]:
    """Return the bounds used by src/sim/obs.ts for x/z normalization."""
    b = (table or {}).get("game", {}).get("world_bounds") or {}
    return (
        float(os.environ.get("WOC_WORLD_MIN_X", b.get("minX", WORLD_MIN_X))),
        float(os.environ.get("WOC_WORLD_MAX_X", b.get("maxX", WORLD_MAX_X))),
        float(os.environ.get("WOC_WORLD_MIN_Z", b.get("minZ", WORLD_MIN_Z))),
        float(os.environ.get("WOC_WORLD_MAX_Z", b.get("maxZ", WORLD_MAX_Z))),
    )
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


def check_table_matches_build(table: dict, layout, obs_size: int | None = None) -> int:
    """Сколько слотов квестов брать. Отказ, если таблица не от этой сборки.

    Порядок квестов в obs — это QUEST_ORDER конкретной сборки, и он НЕ совпадает
    между версиями: у v0.42.2 (224) с v0.40.0 (214) расходится уже со второй
    позиции, то есть позиционный маппинг ведёт агента по чужим координатам. Оракул
    подаётся жёстким входом, поэтому здесь отказ, а не предупреждение. Осознанный
    короткий список (204 — префикс 214-й) включается флагом WOC_QUEST_TABLE_ALLOW_SHORT.

    Вынесено отдельной функцией после разбора: быстрый путь first_target() брал
    min(число квестов в таблице, в obs) и этой проверки не делал — то есть тихо
    считал по чужой таблице. Теперь проверку зовут оба пути.
    """
    n_quests_in_table = len(table["order"])
    n_quests_in_obs = layout.n_quests
    n = min(n_quests_in_table, n_quests_in_obs)
    if n_quests_in_table != n_quests_in_obs:
        msg = (
            f"таблица оракула не от этой сборки: в ней {n_quests_in_table} квестов, "
            f"окружение говорит про {n_quests_in_obs} (obs={obs_size}, "
            f"действий={layout.n_actions}). Сгенерируй таблицу под свою сборку: "
            f"bash tools/make_quest_oracle.sh <тег игры> data/quest_oracle.json; "
            f"если таблица заведомо короче и порядок совпадает по префиксу — "
            f"WOC_QUEST_TABLE_ALLOW_SHORT=1"
        )
        if not os.environ.get("WOC_QUEST_TABLE_ALLOW_SHORT"):
            raise ValueError(msg)
        import warnings
        warnings.warn(msg + f". Используем первые {n}.", stacklevel=2)
    return n


def quest_slots(obs: np.ndarray, table: dict, layout: ObsLayout | None = None,
                n_actions: int | None = None) -> list[tuple[str, str, float]]:
    """[(questId, state, progress)] для всех слотов квестов в obs.

    Раскладка берётся из длины obs (obs_layout), а не из константы: игра меняет
    число слотов способностей, и блок квестов вместе с ними сдвигается.
    Таблица оракула может быть снята с другой версии игры — маппим по quest ID,
    используем только те квесты, которые есть в обоих списках.
    """
    obs = np.asarray(obs, dtype=np.float32).reshape(-1)
    layout = layout or from_obs(obs, n_actions=n_actions)
    n = check_table_matches_build(table, layout, obs_size=obs.shape[0])
    out = []
    for i in range(n):
        qid = table["order"][i]
        base = layout.quest_base + 2 * i
        if base + 1 >= obs.shape[0]:
            break
        state = decode_state(float(obs[base]))
        prog = float(obs[base + 1])
        out.append((qid, state, prog))
    return out


def _bounds_cached(table: dict) -> tuple[float, float, float, float]:
    """world_bounds с кэшем на таблице: в горячем цикле это 4 чтения env на вызов."""
    cached = table.get("_bounds_resolved")
    if cached is not None:
        return cached
    b = world_bounds(table)
    table["_bounds_resolved"] = b
    return b


def first_target(obs: np.ndarray, table: dict, layout: ObsLayout | None = None,
                 n_actions: int | None = None):
    """Первый по порядку незакрытый квест, у которого есть куда идти.

    Возвращает (qid, state, prog, kind, target, quest) или шесть None.

    Отличие от quest_slots() только в цене: тот строит список из 224 кортежей с
    decode_state на каждый, а в шаге обучения нужен ровно первый подходящий. Здесь
    незакрытые слоты отбираются одним numpy-сравнением по всему блоку квестов, и
    Python-работа делается только по ним (обычно 1-3 штуки). Логика выбора цели —
    та же (порядок слотов, приоритет «сдавать → брать → добивать»), эквивалентность
    закреплена тестом tools/test_quest_oracle.py --parity.
    """
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    layout = layout or from_obs(o, n_actions=n_actions)
    # Та же проверка «таблица от этой сборки», что и в quest_slots(): без неё быстрый
    # путь молча считал бы чужую таблицу (поймано tools/test_device.py, проверка 6).
    n = check_table_matches_build(table, layout, obs_size=o.shape[0])
    base = layout.quest_base
    end = min(base + 2 * n, o.shape[0])
    flat = o[base:end]
    pairs = flat[: (flat.shape[0] // 2) * 2].reshape(-1, 2)
    if pairs.size == 0:
        return (None, None, None, None, None, None)
    states, progs = pairs[:, 0], pairs[:, 1]
    # decode_state: >=0.99 done | >=0.5 ready | >0.01 active | иначе untaken.
    for i in np.nonzero(states < 0.99)[0]:
        qid = table["order"][int(i)]
        quest = table["quests"].get(qid) or {}
        state = decode_state(float(states[i]))
        prog = float(progs[i])
        kind, target = _target_for(quest, prog, state)
        if target is not None:
            return qid, state, prog, kind, target, quest
    return (None, None, None, None, None, None)


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


def describe_target(qid, quest, kind, target, state, prog, x, z, facing) -> dict:
    """Собрать ответ оракула для выбранной цели. Одна точка правды для guidance()
    и guidance_from_obs(): раньше формула лежала внутри guidance(), и быстрый путь
    неизбежно разошёлся бы с ней по округлениям."""
    dx, dz = target["x"] - x, target["z"] - z
    dist = float(np.hypot(dx, dz))
    # WoC convention: facing=0 points along +Z; screen-right is (-cos(f), sin(f)).
    # Therefore the world bearing uses atan2(dx, dz), not the mathematical atan2(dz, dx).
    world_angle = float(np.arctan2(dx, dz))
    rel = float(np.arctan2(np.sin(world_angle - facing), np.cos(world_angle - facing)))
    return {
        "quest": qid, "name": quest.get("name"), "quest_state": state,
        "quest_progress": round(prog, 3), "target_kind": kind,
        "target": {"x": round(target["x"], 1), "z": round(target["z"], 1)},
        "dist": round(dist, 1), "dist_norm": round(min(dist / DIST_NORM, DIST_CLAMP), 3),
        "bearing_rel": round(rel, 3),
        "sin": round(float(np.sin(rel)), 3), "cos": round(float(np.cos(rel)), 3),
    }


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
        return describe_target(qid, quest, kind, target, state, prog, x, z, facing)
    return {"quest": None, "name": None, "target_kind": "all_done"}


def guidance_from_obs(obs: np.ndarray, table: dict | None = None,
                      n_actions: int | None = None) -> dict:
    """Самодостаточно: x, z и facing берём из obs (4, 5, 6/7 — obs.ts)."""
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    facing = float(np.arctan2(o[6], o[7]))
    # obs.ts encodes x as x/WORLD_MAX_X, but z is centered/scaled over the full
    # world interval. Multiplying both by 900 (the old implementation) produces
    # systematically wrong quest distances and bearings on the current multi-zone world.
    min_x, max_x, min_z, max_z = _bounds_cached(table)
    x = float(o[4]) * max_x
    z = min_z + ((float(o[5]) + 1.0) * 0.5) * (max_z - min_z)
    layout = from_obs(o, n_actions=n_actions)
    qid, state, prog, kind, target, quest = first_target(o, table, layout=layout)
    if target is None:
        return {"quest": None, "name": None, "target_kind": "all_done"}
    return describe_target(qid, quest, kind, target, state, prog, x, z, facing)


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
