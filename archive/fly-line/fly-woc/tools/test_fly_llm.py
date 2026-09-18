#!/usr/bin/env python3
"""test_fly_llm.py — приёмка «киборга»: LLM выбирает цель, коннектом рулит.

Проверяем ровно те свойства, от которых зависит, можно ли это включать в прогон:

1. БЕЗ LLM ПОВЕДЕНИЕ НЕ МЕНЯЕТСЯ. WOC_LLM=off обязан отдавать бит-в-бит тот же
   5-мерный вектор, что и quest_oracle.oracle_vector. Иначе включение модуля
   сломало бы уже обученный чек-инт, и виноват был бы «киборг».
2. РАЗБОР СТРОГИЙ. Чужой/битый JSON, неизвестный квест, поле вне схемы — это
   исключение и фолбэк, а не «догадка». Агент не имеет права на выдуманный квест.
3. СБОЙ МОДЕЛИ = РАБОТА ПО ПРАВИЛАМ. Таймаут, сеть, мусор на выходе: цель берётся
   из правил, счётчики (fallback/timeouts) растут, источник виден в логе.
4. ВЫБОР ДЕЙСТВИТЕЛЬНО ВЛИЯЕТ. Две разные цели («к сдаче» и «к объективу») дают
   разные векторы, и вектор сдачи совпадает с геометрией quest_oracle по той же точке.
5. ЦИКЛ НЕ БЛОКИРУЕТ ТАКТ. Фоновый планировщик обновляет цель реже игры, отдаёт
   последнюю готовую, помечает устаревшие (stale) и корректно останавливается.
6. КАНАЛЫ МУХИ НЕ ВРУТ. Сдвиг 13 каналов ограничен по модулю и не касается
   реактивных (hp/бой/gcd): LLM не имеет права искажать коннектому картину мира.

Запуск (без сети и без игры): python3 tools/test_fly_llm.py
Код возврата 1, если хоть одна проверка не прошла.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["WOC_LLM"] = "off"          # база: ни одного внешнего вызова

import numpy as np                                              # noqa: E402

import fly_llm as FL                                            # noqa: E402
import quest_oracle as qo                                       # noqa: E402
from obs_layout import from_obs                                 # noqa: E402

TABLE = qo.load_table()
N_ACTIONS = 61


def make_obs(quest_state: float = 0.33, x: float = -0.1, z: float = -0.05) -> np.ndarray:
    """obs сборки obs=607: первый квест в заданном состоянии, герой в заданной точке."""
    o = np.zeros(607, dtype=np.float32)
    o[0], o[1], o[11] = 0.7, 0.9, 0.0
    o[4], o[5], o[6], o[7] = x, z, 0.0, 1.0
    L = from_obs(o, n_actions=N_ACTIONS)
    o[L.quest_base] = quest_state
    return o


class BadJSON:
    name = "bad-json"

    def complete(self, prompt: str, timeout_s: float, state=None) -> str:
        return "конечно! вот план: иди на север))"


class TimeoutBackend:
    name = "timeout"

    def complete(self, prompt: str, timeout_s: float, state=None) -> str:
        raise TimeoutError("сервер не ответил")


class UnknownQuest:
    name = "unknown-quest"

    def complete(self, prompt: str, timeout_s: float, state=None) -> str:
        return json.dumps({"quest": "q_не_существует", "mode": "quest", "go": "objective",
                           "objective_index": 0, "reason": "выдумал"})


TESTS: list[tuple[str, callable]] = []


def test(fn: callable) -> callable:
    TESTS.append((fn.__doc__ or fn.__name__, fn))
    return fn


# --------------------------------------------------------------------- проверки


@test
def t_off_is_bitwise_baseline() -> tuple[bool, str]:
    """WOC_LLM=off: вектор политики бит-в-бит совпадает с оракулом (чек-инт цел)."""
    obs = make_obs()
    aux, goal = FL.aux_for_policy(obs, loop=FL.CortexLoop(FL.FakeCortex()), table=TABLE)
    ref = qo.oracle_vector(obs, table=TABLE)
    return (np.array_equal(aux, ref) and goal.source == "off",
            f"равны={np.array_equal(aux, ref)} источник={goal.source}")


@test
def t_state_reads_quest_from_obs() -> tuple[bool, str]:
    """Состояние для LLM: незакрытый квест и подсказка оракула на месте."""
    st = FL.state_from_obs(make_obs(), table=TABLE)
    ok = bool(st.open_quests) and st.guiding.get("target_kind") is not None
    q = st.open_quests[0] if st.open_quests else {}
    return ok, f"квестов={len(st.open_quests)} первый={q.get('id')} цель={st.guiding.get('target_kind')}"


@test
def t_fake_is_deterministic() -> tuple[bool, str]:
    """Правиловый кортекс детерминирован: две цели подряд совпадают по всем полям."""
    loop = FL.CortexLoop(FL.FakeCortex(), timeout_s=0.05)
    st = FL.state_from_obs(make_obs(), table=TABLE)
    a, b = loop.plan(st), loop.plan(st)
    same = a.as_dict() | {"latency_s": 0.0, "source": ""} == b.as_dict() | {"latency_s": 0.0, "source": ""}
    return same, f"цель={a.quest}/{a.mode}/{a.go} совпали={same}"


@test
def t_strict_parse_rejects_junk() -> tuple[bool, str]:
    """Строгий разбор: мусор и выдуманный квест отклоняются, а не «угадываются»."""
    st = FL.state_from_obs(make_obs(), table=TABLE)
    fails = []
    for backend in (BadJSON(), UnknownQuest()):
        try:
            FL.parse_goal(backend.complete("", 0.0), st)
            fails.append(backend.name)
        except ValueError:
            pass
    try:                                   # поле вне схемы
        FL.parse_goal(json.dumps({"quest": None, "mode": "летать", "go": "objective",
                                  "objective_index": 0, "reason": "x"}), st)
        fails.append("mode-вне-схемы")
    except ValueError:
        pass
    return (not fails), f"не отбитых мусорных ответов: {fails or 'нет'}"


@test
def t_fallback_on_bad_json() -> tuple[bool, str]:
    """Битый JSON модели -> цель по правилам, счётчик fallback растёт."""
    loop = FL.CortexLoop(BadJSON(), timeout_s=0.2)
    goal = loop.plan(FL.state_from_obs(make_obs(), table=TABLE))
    s = loop.stats.summary()
    return (goal.source == "fallback" and s["fallback"] == 1 and goal.quest is not None,
            f"источник={goal.source} fallback={s['fallback']} цель={goal.quest} причина={goal.reason[:40]!r}")


@test
def t_fallback_on_timeout() -> tuple[bool, str]:
    """Таймаут сервера модели -> цель по правилам, отдельный счётчик timeouts."""
    loop = FL.CortexLoop(TimeoutBackend(), timeout_s=0.2)
    goal = loop.plan(FL.state_from_obs(make_obs(), table=TABLE))
    s = loop.stats.summary()
    return (goal.source == "fallback" and s["timeouts"] == 1 and "таймаут" in goal.reason,
            f"timeouts={s['timeouts']} причина={goal.reason[:50]!r}")


@test
def t_fenced_json_is_normalized() -> tuple[bool, str]:
    """markdown-обёртка снимается (формат), но семантика всё равно проверяется."""
    st = FL.state_from_obs(make_obs(), table=TABLE)
    raw = '```json\n{"quest": "%s", "mode": "quest", "go": "objective", "objective_index": 0, "reason": "ok"}\n```' % st.open_quests[0]["id"]
    goal = FL.parse_goal(raw, st)
    return goal.quest == st.open_quests[0]["id"], f"разобран квест={goal.quest} из обёртки ```json"


@test
def t_veto_stops_nonsense() -> tuple[bool, str]:
    """Вето: бессмысленный (но валидный по схеме) план отклоняется, работает фолбэк."""
    st = FL.state_from_obs(make_obs(), table=TABLE)          # hp 0.7, не в бою
    bad = ('{"quest": null, "mode": "survive", "go": "turnin", "objective_index": 0, '
           '"reason": "модель решила по-своему"}')

    class Nonsense:
        name = "nonsense"

        def complete(self, prompt: str, timeout_s: float, state=None) -> str:
            return bad

    loop = FL.CortexLoop(Nonsense(), timeout_s=0.2)
    goal = loop.plan(st)
    s = loop.stats.summary()
    reasons = [r for r in (FL.veto(FL.Goal(quest=None, mode="quest"), st),
                           FL.veto(FL.Goal(quest=st.open_quests[0]["id"],
                                           mode="survive"), st),
                           FL.veto(FL.Goal(quest=st.open_quests[0]["id"], go="turnin"), st))]
    ok = (goal.source == "fallback" and s["vetoed"] == 1 and all(reasons)
          and "вето" in goal.reason)
    return ok, f"вето={s['vetoed']} причины={[r[:28] for r in reasons]} цель={goal.quest}"


@test
def t_goal_changes_guidance() -> tuple[bool, str]:
    """Смена цели меняет вектор: «к сдаче» != «к объективу», геометрия совпадает с оракулом."""
    obs = make_obs()
    st = FL.state_from_obs(obs, table=TABLE)
    qid = st.open_quests[0]["id"]
    a = FL.goal_vector(FL.Goal(quest=qid, go="objective"), obs, TABLE)
    b = FL.goal_vector(FL.Goal(quest=qid, go="turnin"), obs, TABLE)
    # независимая проверка: считаем ту же точку сдачи тем же кодом оракула
    quest = TABLE["quests"][qid]
    x = float(obs[4]) * qo.WORLD_MAX_X
    z = qo.WORLD_MIN_Z + ((float(obs[5]) + 1.0) * 0.5) * (qo.WORLD_MAX_Z - qo.WORLD_MIN_Z)
    facing = float(np.arctan2(obs[6], obs[7]))
    slots = {q: (s, p) for q, s, p in qo.quest_slots(obs, TABLE)}
    state, prog = slots[qid]
    d = qo.describe_target(qid, quest, "turnin", quest["turnIn"], state, prog, x, z, facing)
    ref = np.asarray([d["dist_norm"], d["sin"], d["cos"],
                      1.0 if state == "active" else 0.0], dtype=np.float32)
    ok = (a.shape == b.shape == (5,)) and not np.allclose(a, b) and np.allclose(b[:4], ref, atol=2e-3)
    return ok, f"vector(objective)={np.round(a, 3).tolist()} vector(turnin)={np.round(b, 3).tolist()}"


@test
def t_missing_quest_is_neutral() -> tuple[bool, str]:
    """Если LLM-цель недоступна, вектор нейтрален (не «стоим на цели»), а не мусор."""
    v = FL.goal_vector(FL.Goal(quest=None), make_obs(), TABLE)
    return (np.allclose(v, [qo.DIST_CLAMP, 0, 0, 0, 0]),
            f"вектор={np.round(v, 3).tolist()}")


@test
def t_channel_bias_is_bounded() -> tuple[bool, str]:
    """Сдвиг каналов ограничен и не трогает реактивные (hp/бой/gcd/цель)."""
    turnin = FL.channel_bias(FL.Goal(go="turnin"))
    explore = FL.channel_bias(FL.Goal(mode="explore", go="objective", quest=None))
    # допуск 1e-6: значения лежат в float32, 0.2f > 0.2 в double
    ok = (float(np.abs(turnin).max()) <= 0.2 + 1e-6 and np.allclose(turnin[:11], 0.0)
          and turnin[11] > 0 and turnin[12] > 0 and np.allclose(explore, 0.0))
    return ok, f"turnin={np.round(turnin, 2).tolist()} explore пусто={bool(np.allclose(explore, 0.0))}"


@test
def t_mode_one_hot() -> tuple[bool, str]:
    """Режим идёт в политику отдельным входом: one-hot по фиксированному порядку MODES."""
    v = FL.mode_one_hot(FL.Goal(mode="survive"))
    ok = v.shape == (len(FL.MODES),) and v.sum() == 1.0 and v[FL.MODES.index("survive")] == 1.0
    return ok, f"MODES={FL.MODES} вектор={v.tolist()}"


@test
def t_background_loop_nonblocking() -> tuple[bool, str]:
    """Фоновый кортекс обновляет цель и не блокирует вызывающего."""
    obs = make_obs()
    loop = FL.CortexLoop(FL.FakeCortex(), period_s=0.02, timeout_s=0.1)
    loop.start(lambda: FL.state_from_obs(obs, table=TABLE))
    t0 = time.perf_counter()
    goal = None
    for _ in range(40):
        goal = loop.current()
        if goal.source == "llm":
            break
        time.sleep(0.02)
    dt = time.perf_counter() - t0
    loop.stop()
    ok = goal is not None and goal.source == "llm" and dt < 2.0 and loop.stats.summary()["ok"] >= 1
    return ok, f"источник={goal.source if goal else None} за {dt:.2f}с вызовов={loop.stats.summary()['ok']}"


@test
def t_stale_goal_is_marked() -> tuple[bool, str]:
    """Устаревшая цель помечается stale: сбой кортекса видно, а не «залипание» молча."""
    loop = FL.CortexLoop(FL.FakeCortex(), stale_s=0.01)
    loop.goal = FL.Goal(quest="q", source="llm")
    loop._last_ok = time.time() - 5.0                     # noqa: SLF001 (тест внутренностей)
    g = loop.current()
    return (g.source == "stale" and loop.stats.summary()["stale"] == 1,
            f"источник={g.source} stale={loop.stats.summary()['stale']}")


def main() -> int:
    print("ПРИЁМКА LLM-КОРТЕКСА (киборг: LLM планирует, коннектом рулит)")
    print(f"  таблица: {len(TABLE['quests'])} квестов | схема цели: "
          f"{len(FL.GOAL_SCHEMA['required'])} обязательных полей | режимы: {FL.MODES}")
    bad = 0
    for label, fn in TESTS:
        try:
            ok, detail = fn()
        except Exception as exc:                            # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"  {'OK  ' if ok else 'FAIL'} {label}\n        {detail}")
        bad += not ok
    print(f"ИТОГ: {len(TESTS) - bad}/{len(TESTS)} пройдено")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
