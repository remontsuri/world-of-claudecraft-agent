"""LLM-кортекс поверх замороженного коннектома: киборг, где LLM планирует, а муха рулит.

Разделение ролей (двухуровневая схема, как в задачах LLM+локальный контроллер):
    LLM (1-2 Гц)      — ЧТО делать: какой незакрытый квест брать, к кому идти
                        (к цели / к выдающему / на сдачу), какая цель по типу.
    коннектом + PPO   — КАК делать: реактивное управление на каждом шаге игры
    (4 решения/с)       (13 инженерных каналов -> 8835 клеток -> 82 DN -> 61 действие).

Почему нельзя «просто пустить LLM в такт игры»: шаг игры — 4 раза в секунду, а
декодирование маленькой модели — сотни миллисекунд на ответ. Поэтому LLM вызывается
на границах решений (редко), а не между кадрами; в такте живёт только замороженный
коннектом. Это ровно тот приём, который в литературе снимает конфликт частот
(arXiv 2609.05133: LLM на границах раундов, локальный контроллер на тике).

Что даёт LLM ровно один рычаг: выбор цели. Технически — он выбирает, на какой
пункт квеста смотрит 5-мерный вектор-ориентир, который readout уже потребляет
(quest_oracle.oracle_vector: [dist_norm, sin, cos, active, ready]). Значит
включается БЕЗ переобучения — фаза 1. Дополнительный вход «режим» (4 one-hot)
требует переобучения readout — фаза 2, флаг есть, по умолчанию выключен.

Честные границы:
  * LLM не пишет в коннектом и не выбирает из 61 действия — это делает readout;
  * при любом сбое LLM (нет сервера, таймаут, невалидный JSON) работает
    детерминированный фолбэк по правилам оракула, и это видно в статистике
    (source = llm / fallback / stale), а не молча;
  * модель не «понимает» игру: она читает компактное состояние и таблицу квестов.

Проверено на MaleCNS-схеме проекта: 224 квеста в data/quest_oracle.json, obs=607.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import numpy as np

import quest_oracle as qo

# ---------------------------------------------------------------- конфигурация

MODES = ("survive", "quest", "earn", "explore")
GO = ("objective", "giver", "turnin")

GOAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "quest": {"type": ["string", "null"]},
        "mode": {"type": "string", "enum": list(MODES)},
        "go": {"type": "string", "enum": list(GO)},
        "objective_index": {"type": "integer", "minimum": 0, "maximum": 7},
        "reason": {"type": "string", "maxLength": 160},
    },
    "required": ["quest", "mode", "go", "objective_index", "reason"],
    "additionalProperties": False,
}

TIMEOUT_S = float(os.environ.get("WOC_LLM_TIMEOUT", "1.5"))
PERIOD_S = float(os.environ.get("WOC_LLM_PERIOD", "2.0"))
STALE_S = float(os.environ.get("WOC_LLM_STALE", "6.0"))
MODE = os.environ.get("WOC_LLM", "off").strip().lower()   # off | fake | server
URL = os.environ.get("WOC_LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODEL = os.environ.get("WOC_LLM_MODEL", "local")


# ---------------------------------------------------------------- структуры


@dataclass
class Goal:
    """Решение кортекса. Ровно то, что LLM имеет право выбрать."""

    quest: str | None = None
    mode: str = "quest"
    go: str = "objective"
    objective_index: int = 0
    reason: str = ""
    source: str = "fallback"      # llm | fallback | stale
    latency_s: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CortexState:
    """Всё, что LLM видит. Никаких пикселей и никакой внутренней активности схемы."""

    step: int = 0
    hp: float = 1.0
    resource: float = 1.0
    in_combat: bool = False
    x: float = 0.0
    z: float = 0.0
    open_quests: list[dict] = field(default_factory=list)
    guiding: dict = field(default_factory=dict)
    last_reward: float = 0.0
    deaths: int = 0
    fly_state: dict = field(default_factory=dict)   # сводка активности мозга (DN), см. fly_lm_brain

    def prompt(self) -> str:
        return (
            "Ты — планировщик в голове мухи, которая играет в WoW-подобную игру.\n"
            "Муха-коннектом управляет лапами сама: ты выбираешь только ЦЕЛЬ.\n"
            f"Состояние: {json.dumps(self.as_dict(), ensure_ascii=False)}\n"
            + (f"{self.fly_state['text']}\n" if self.fly_state.get("text") else "")
            + "Правила: бери незакрытый квест из open_quests; go=turnin если готов сдать "
            "(state=ready), иначе objective; mode=survive если hp<0.35 и в бою.\n"
            'Ответ — ТОЛЬКО JSON, без пояснений и без markdown, ровно такой формы: '
            '{"quest": "<id из open_quests или null>", "mode": "survive|quest|earn|explore", '
            '"go": "objective|giver|turnin", "objective_index": 0, "reason": "<коротко>"}'  
        )

    def as_dict(self) -> dict:
        return {
            "step": self.step, "hp": round(self.hp, 2), "resource": round(self.resource, 2),
            "in_combat": bool(self.in_combat), "x": round(self.x, 1), "z": round(self.z, 1),
            "open_quests": self.open_quests[:6], "guiding": self.guiding,
            "deaths": self.deaths, "fly_state": self.fly_state,
        }


class Backend(Protocol):
    def complete(self, prompt: str, timeout_s: float,
                 state: "CortexState | None" = None) -> str: ...


# ---------------------------------------------------------------- бэкенды


class FakeCortex:
    """Детерминированный «планировщик по правилам». Он же фолбэк, он же эталон для тестов.

    Не притворяется LLM: это правила оракула, вывернутые в тот же формат ответа.
    Так живой прогон не зависит от того, поднят ли сервер модели.
    """

    name = "fake-rules"

    def complete(self, prompt: str, timeout_s: float,
                 state: "CortexState | None" = None) -> str:
        if state is None:                     # офлайн-вызов без состояния: разбираем промпт
            chunk = prompt[prompt.index("Состояние: ") + len("Состояние: "):]
            chunk = chunk[: chunk.index("\nПравила:")]
            state = CortexState(**json.loads(chunk))
        quests = state.open_quests or []
        # Вариант выбора квеста — только для демонстраций «рычаг действительно
        # управляет агентом»: разные варианты ведут муху в разные концы мира.
        # По умолчанию first (первый незакрытый), как в правилах.
        variant = os.environ.get("WOC_LLM_FAKE_VARIANT", "first").lower()
        if not quests:
            pick = None
        elif variant == "last":
            pick = quests[-1]
        elif variant == "ready_first":
            pick = next((q for q in quests if q.get("state") == "ready"), quests[0])
        else:
            pick = quests[0]
        mode = "survive" if (state.in_combat and state.hp < 0.35) else "quest"
        go = "turnin" if (pick and pick.get("state") == "ready") else "objective"
        goal = {
            "quest": pick["id"] if pick else None,
            "mode": mode,
            "go": go if pick else "objective",
            "objective_index": 0,
            "reason": "правило: первый незакрытый квест",
        }
        return json.dumps(goal, ensure_ascii=False)


class LlamaServerBackend:
    """llama.cpp / Ollama-совместимый сервер с жёсткой JSON-схемой.

    Схема передаётся в response_format, поэтому сервер (GBNF/грамматика) физически
    не может выдать невалидный JSON. Это важно здесь: сбой разбора — это не «модель
    глупая», а сломанный такт агента.
    """

    def __init__(self, url: str = URL, model: str = MODEL, temperature: float = 0.2):
        self.url, self.model, self.temperature = url, model, temperature
        self.name = f"llama-server:{model}"

    def complete(self, prompt: str, timeout_s: float,
                 state: "CortexState | None" = None) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": 120,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "fly_goal", "schema": GOAL_SCHEMA}},
        }
        req = urllib.request.Request(  # noqa: S310 (локальный сервер)
            self.url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode())
        return payload["choices"][0]["message"]["content"]


def make_backend(name: str | None = None) -> Backend:
    name = (name or MODE).lower()
    if name == "server":
        return LlamaServerBackend()
    return FakeCortex()


# ---------------------------------------------------------------- разбор и выбор


def open_quests(obs: np.ndarray, table: dict | None = None) -> list[dict]:
    """Незакрытые квесты в порядке QUEST_ORDER с читаемой формулировкой цели."""
    table = table or qo.load_table()
    out = []
    for qid, state, prog in qo.quest_slots(obs, table):
        if state == "done":
            continue
        quest = table["quests"].get(qid) or {}
        kind, target = qo._target_for(quest, prog, state)  # noqa: SLF001 (одна точка правды)
        objectives = quest.get("objectives") or [{}]
        obj = objectives[0]
        out.append({
            "id": qid, "name": quest.get("name"), "state": state,
            "progress": round(float(prog), 3), "xp": quest.get("xp"),
            "objective": {"type": obj.get("type"), "count": obj.get("count"),
                          "target_mob": obj.get("targetMobId")},
            "next_target_kind": kind,
            "needs": quest.get("requires"),
            "_target": target,
        })
    return out


def extract_json(raw: str) -> str:
    """Достать объект из ответа модели.

    Снимаем markdown-обёртку и лишний текст по краям: маленькие модели через
    transformers почти всегда пишут ```json ... ```. Это нормализация ФОРМАТА,
    а не поблажка по смыслу — всё содержание ниже проверяется строго.
    При работе через llama.cpp с response_format этого шага не требуется:
    грамматика (GBNF) не даёт модели выйти за схему вообще.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start, depth, in_str, esc = -1, 0, False, False
    for i, ch in enumerate(text):
        if in_str:
            esc = (ch == "\\" and not esc)
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start:i + 1]
    raise ValueError("в ответе модели нет JSON-объекта")


def veto(goal: Goal, state: CortexState) -> str | None:
    """Вето правил: LLM предлагает, но за жизнь агента отвечают правила.

    Причина появления (замер на живой модели, Qwen2.5-0.5B): модель выдаёт
    схема-валидный, но бессмысленный план — quest=null при 224 открытых квестах
    и mode=survive при 62% HP вне угрозы. Такой план превращает агента в стоячего.
    Поэтому: форма проверяется схемой, а ЗДРАВЫЙ СМЫСЛ — здесь.
    Возвращает текст причины вето или None, если план принимается.
    """
    if goal.quest is None and state.open_quests:
        return "нет цели, хотя открытые квесты есть"
    if goal.mode == "survive" and not (state.in_combat and state.hp < 0.35):
        return "выживание без угрозы (не в бою или hp>=0.35)"
    if goal.quest is not None:
        cur = next((q for q in state.open_quests if q["id"] == goal.quest), None)
        if cur and goal.go == "turnin" and cur.get("state") != "ready":
            return "сдача, когда квест ещё не готов"
    return None


def parse_goal(raw: str, state: CortexState) -> Goal:
    """Строгая проверка ответа модели: схема, затем вето правил."""
    data = json.loads(extract_json(raw))
    if not isinstance(data, dict):
        raise ValueError("ответ не объект")
    missing = set(GOAL_SCHEMA["required"]) - set(data)
    if missing:
        raise ValueError(f"нет полей: {sorted(missing)}")
    if data["mode"] not in MODES:
        raise ValueError(f"mode вне схемы: {data['mode']!r}")
    if data["go"] not in GO:
        raise ValueError(f"go вне схемы: {data['go']!r}")
    qi = int(data["objective_index"])
    if qi < 0:
        raise ValueError("objective_index < 0")
    ids = {q["id"] for q in state.open_quests}
    if data["quest"] is not None and data["quest"] not in ids:
        if data["quest"] not in {q["id"] for q in state.open_quests}:
            # квест может быть закрыт/не из списка — не выдумываем, отдаём фолбэку
            raise ValueError(f"квеста {data['quest']!r} нет среди незакрытых")
    return Goal(quest=data["quest"], mode=data["mode"], go=data["go"],
                objective_index=qi, reason=str(data["reason"])[:160], source="llm")


def goal_from_rules(state: CortexState) -> Goal:
    """Фолбэк: то же правило, что в FakeCortex, но без вызова модели и без сети."""
    return Goal(**json.loads(FakeCortex().complete("", 0.0, state)), source="fallback")


# ---------------------------------------------------------------- выход в политику


def _target_for_goal(goal: Goal, quest: dict, state: str, prog: float,
                     table: dict) -> tuple[str, dict | None]:
    """Куда идти по выбранной цели: сдача > выдача > объектив (порядок продуктивности)."""
    if goal.go == "turnin" and quest.get("turnIn"):
        return "turnin", quest["turnIn"]
    if goal.go == "giver" and quest.get("giver"):
        return "giver", quest["giver"]
    kind, target = qo._target_for(quest, prog, state)  # noqa: SLF001
    return kind, target


def goal_description(goal: Goal, obs: np.ndarray, table: dict | None = None) -> dict | None:
    """Куда именно ведёт выбранная цель: та же геометрия, что у оракула (одна формула).

    Нужна карте/отчёту: по вектору видно «куда идти», а по описанию — «к какой точке».
    """
    table = table or qo.load_table()
    slots = {qid: (st, pr) for qid, st, pr in qo.quest_slots(obs, table)}
    if goal.quest is None or goal.quest not in slots:
        return None
    state, prog = slots[goal.quest]
    quest = table["quests"].get(goal.quest) or {}
    kind, target = _target_for_goal(goal, quest, state, prog, table)
    if target is None:
        return None
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    x = float(o[4]) * qo.WORLD_MAX_X
    z = qo.WORLD_MIN_Z + ((float(o[5]) + 1.0) * 0.5) * (qo.WORLD_MAX_Z - qo.WORLD_MIN_Z)
    facing = float(np.arctan2(o[6], o[7]))
    desc = qo.describe_target(goal.quest, quest, kind, target, state, prog, x, z, facing)
    desc["goal_mode"], desc["goal_go"], desc["goal_source"] = goal.mode, goal.go, goal.source
    return desc


def goal_vector(goal: Goal, obs: np.ndarray, table: dict | None = None) -> np.ndarray:
    """5-мерный вектор-ориентир под выбранную LLM цель — тот же формат, что у оракула.

    Именно поэтому включение LLM не требует переобучения readout: он уже потребляет
    такой вектор (quest_oracle.oracle_vector), меняется только источник выбора цели.
    """
    desc = goal_description(goal, obs, table)
    if desc is None:
        return np.asarray([qo.DIST_CLAMP, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    return np.asarray([desc["dist_norm"], desc["sin"], desc["cos"],
                       desc["active"], desc["ready"]], dtype=np.float32)


def mode_one_hot(goal: Goal) -> np.ndarray:
    """Режим как отдельный вход readout (фаза 2: требует переобучения)."""
    v = np.zeros(len(MODES), dtype=np.float32)
    v[MODES.index(goal.mode)] = 1.0
    return v


def channel_bias(goal: Goal, scale: float = 0.2) -> np.ndarray:
    """Слабый сдвиг 13 инженерных каналов под выбранную цель.

    Трогаем только два канала, которые отвечают за «взаимодействие/квест», и никогда
    не трогаем реактивные (hp/бой/gcd) — иначе LLM начал бы врать коннектому о мире.
    Всё остальное — дело тела.
    """
    bias = np.zeros(13, dtype=np.float32)
    if goal.go in ("turnin", "giver"):
        bias[11] = scale          # interact_prox: NPC/сдача ближе по смыслу
        bias[12] = scale          # quest_signal: «есть что сдавать»
    elif goal.mode == "quest":
        bias[12] = scale * 0.5
    return bias


# ---------------------------------------------------------------- цикл кортекса


@dataclass
class CortexStats:
    calls: int = 0
    ok: int = 0
    fallback: int = 0
    stale: int = 0
    timeouts: int = 0
    vetoed: int = 0
    latencies: deque = field(default_factory=lambda: deque(maxlen=64))

    def summary(self) -> dict:
        lat = sorted(self.latencies)
        def pct(p: float) -> float:
            return round(lat[min(len(lat) - 1, int(p * len(lat)))], 3) if lat else 0.0
        return {"calls": self.calls, "ok": self.ok, "fallback": self.fallback,
                "stale": self.stale, "timeouts": self.timeouts, "vetoed": self.vetoed,
                "lat_p50": pct(0.5), "lat_p95": pct(0.95)}


class CortexLoop:
    """Фоновый планировщик: обновляет цель реже, чем идёт игра, и никогда не блокирует такт."""

    def __init__(self, backend: Backend | None = None, period_s: float = PERIOD_S,
                 stale_s: float = STALE_S, timeout_s: float = TIMEOUT_S):
        self.backend = backend or make_backend()
        self.period_s, self.stale_s, self.timeout_s = period_s, stale_s, timeout_s
        self.goal = Goal(source="fallback")
        self.stats = CortexStats()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_ok = 0.0

    # --- синхронный вызов (для тестов и офлайн-прогонов)
    def plan(self, state: CortexState) -> Goal:
        prompt = state.prompt()
        t0 = time.perf_counter()
        self.stats.calls += 1
        try:
            raw = self.backend.complete(prompt, self.timeout_s, state)
            goal = parse_goal(raw, state)
            why = veto(goal, state)
            if why is not None:               # план схеме соответствует, но вреден
                self.stats.vetoed += 1
                raise ValueError(f"вето: {why}")
            goal.latency_s = time.perf_counter() - t0
            self.stats.ok += 1
            self.stats.latencies.append(goal.latency_s)
            self._last_ok = time.time()
            return goal
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            self.stats.timeouts += 1
            self.stats.fallback += 1
            g = goal_from_rules(state)
            g.reason = f"таймаут/сеть ({type(exc).__name__}: {exc}) · правило: {g.reason}"
            return g
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.stats.fallback += 1
            g = goal_from_rules(state)
            # текст исключения не теряем: именно в нём видно «вето: …» или причину
            # отказа схемы — иначе сбой модели выглядел бы как обычное решение правил
            g.reason = f"фолбэк ({type(exc).__name__}: {exc}) · правило: {g.reason}"
            return g

    # --- фоновый режим
    def start(self, state_fn) -> None:
        def run() -> None:
            while not self._stop.is_set():
                state = state_fn()
                goal = self.plan(state)
                with self._lock:
                    self.goal = goal
                self._stop.wait(self.period_s)
        self._thread = threading.Thread(target=run, name="fly-cortex", daemon=True)
        self._thread.start()

    def current(self) -> Goal:
        with self._lock:
            goal = self.goal
        if goal.source == "llm" and (time.time() - self._last_ok) > self.stale_s:
            self.stats.stale += 1
            g = Goal(**goal.as_dict())
            g.source = "stale"
            return g
        return goal

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


# ---------------------------------------------------------------- сборка состояния


def state_from_obs(obs: np.ndarray, step: int = 0, table: dict | None = None,
                   deaths: int = 0, last_reward: float = 0.0) -> CortexState:
    """Состояние для LLM: только то, что LLM реально может использовать."""
    table = table or qo.load_table()
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    quests = open_quests(o, table)
    for q in quests:
        q.pop("_target", None)
    guide = qo.guidance_from_obs(o, table)
    guide = {k: guide.get(k) for k in ("quest", "name", "target_kind", "quest_state",
                                       "dist", "bearing_rel")}
    return CortexState(step=step, hp=float(o[0]), resource=float(o[1]),
                       in_combat=bool(o[11]), x=float(o[4]) * qo.WORLD_MAX_X,
                       z=qo.WORLD_MIN_Z + ((float(o[5]) + 1.0) * 0.5) * (qo.WORLD_MAX_Z - qo.WORLD_MIN_Z),
                       open_quests=quests, guiding=guide, last_reward=last_reward,
                       deaths=deaths)


def aux_for_policy(obs: np.ndarray, loop: CortexLoop | None, table: dict | None = None,
                   mode: str | None = None) -> tuple[np.ndarray, Goal]:
    """Сколько чисел получает readout и откуда.

    WOC_LLM=off  -> ровно как сегодня: вектор оракула, поведение не меняется;
    WOC_LLM=fake/server -> вектор строится по ЦЕЛИ, ВЫБРАННОЙ кортексом.
    Формат вектора в обоих случаях одинаковый, поэтому чек-инт readout не меняется.
    """
    table = table or qo.load_table()
    mode = (mode or MODE).lower()
    if loop is None or mode == "off":
        return qo.oracle_vector(obs, table=table), Goal(source="off", reason="LLM выключен")
    goal = loop.current()
    return goal_vector(goal, obs, table), goal


def main() -> int:
    """Самопроверка: состояние -> цель -> вектор политики, без игры и без сети."""
    table = qo.load_table()
    obs = np.zeros(607, dtype=np.float32)
    obs[0], obs[1], obs[11] = 0.7, 0.9, 0.0
    obs[4], obs[5], obs[6], obs[7] = -0.1, -0.05, 0.0, 1.0
    from obs_layout import from_obs
    L = from_obs(obs)
    obs[L.quest_base] = 0.33          # первый квест взят и активен
    loop = CortexLoop(FakeCortex(), timeout_s=0.1)
    st = state_from_obs(obs, table=table)
    goal = loop.plan(st)
    print("состояние:", json.dumps(st.as_dict(), ensure_ascii=False)[:200])
    print("цель:", json.dumps(goal.as_dict(), ensure_ascii=False))
    aux, g = aux_for_policy(obs, loop, table)
    print("вектор политики:", np.round(aux, 3).tolist(), "источник:", g.source)
    print("статистика:", loop.stats.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
