# LLM Brain для WoC-агента — дизайн (spec)

Дата: 2026-08-23. Статус: утверждён пользователем («давай»).
Живые пробы Qwen3.6-35B-A3B (:8081, llama.cpp b10000, 128K ctx) — все критерии пройдены
(см. «Верификация» внизу).

## 1. Зачем это нужно (пользовательская перспектива)

Сегодня агент — табличный Q-learning без знания о мире: он не понимает, что квест в фазе
ACTIVE бессмысленно ACCEPT-ить, не умеет объяснить свой выбор и повторяет одни и те же
ошибки. После этого изменения стратегические решения принимает локальная LLM
(Qwen3.6-35B, уже стоит на машине), а Q-learning остаётся быстрым исполнителем внутри
фазы. Со стороны это выглядит так: агент перестаёт молотить бесполезные действия, его
решения можно прочитать (`reason`), и он накапливает опыт попыток по каждому квесту.

## 2. Принципы (утверждены пользователем)

1. **LLM = мозг, Q-learning = рефлексы.** LLM выбирает ЦЕЛЬ из фиксированного enum'а;
   выбор скилла внутри цели остаётся за существующим GoalManager/Q-policy.
2. **Никакого низкоуровневого управления от LLM** — ни координат, ни клавиш. Контракт:
   `{goal, reason}`, где `goal` ∈ {ACCEPT, DO_OBJECTIVE, RETURN_TO_GIVER, TURN_IN,
   SELL_REPAIR, HEAL, SURVIVE}. Валидация json_schema strict на сервере + повторная
   валидация enum'а у нас.
3. **Не трогаем bridge и skills.** LLM ставится НАД работающими WorldState +
   GoalFSM + policy + replay. Bridge (:8791) не изменяется.
4. **Отказобезопасность:** сервер недоступен / мусор / таймаут → работаем как сегодня
   (чистый FSM+Q). Нулевая деградация.
5. **Три уровня памяти:**
   - pretrained — сама модель;
   - world memory — `world_memory.json` (уже есть: quest→giver, vendors);
   - episodic memory — НОВОЕ: `episodic_log.jsonl`, запись каждой попытки per quest.

## 3. Компоненты

### 3.1 `python/llm_brain.py` (новый)

```python
class LLMBrain:
    def __init__(self, base_url="http://127.0.0.1:8081", timeout=20.0,
                 journal_dir=None): ...
    def should_consult(self, fsm, step_idx, recent_failures) -> bool
    def decide(self, world_json: dict) -> dict | None   # {goal, reason} или None
    def _prompt(self, world: dict, failures: list, lessons: list) -> tuple[str, str]
```

- `should_consult`: True при (a) смене фазы FSM, (b) >=3 фейла подряд,
  (c) новый quest_id, (d) каждые 50 шагов. Иначе False (экономия латентности).
- `decide`: POST `/v1/chat/completions`, temperature=0, max_tokens<=120,
  `response_format=json_schema` (strict, enum целей). Таймаут → None.
- Ответ валидируем: goal ∈ enum, иначе None.

### 3.2 Эпизодическая память `python/episodic_log.jsonl` (новый формат)

Одна строка = одна попытка:
```json
{"t": 1787..., "quest": "q_bones", "step": 4310, "action": "turn_in_quest",
 "result": "FAILURE", "reason": "wrong_npc_distance_3.6", "hp_frac": 0.8,
 "phase": "TURN_IN"}
```
Пишется после каждого шага (уже имеющийся `rec`). Читается хвост последних 5 записей
по текущему quest_id + последние 3 урока SelfReflection (TTL уже реализован).

### 3.3 Интеграция в `play_autonomous.py` (минимальные точки входа)

- Переключатель: env `WOC_BRAIN=on|off` (default off — A/B сравнение прогонов).
- После `goal_fsm.update_from_world(...)` и перед `agent.step()`:
  если `brain.should_consult(...)` → `decide()` → при валидном ответе
  `goal_fsm.set(brain_goal)` (+ лог `[brain] goal=X reason=...`).
- Пишем episodic-запись после каждого шага.

### 3.4 Промпт (зафиксирован, живьём проверен)

System: правила фаз (ACCEPT только AVAILABLE; DO_OBJECTIVE при ACTIVE+progress<required;
RETURN_TO_GIVER при готовых целях и giver>7yd; TURN_IN только READY и рядом; HEAL при
hp<0.35; учитывать recent_failures). User: компактный JSON мира + failures + lessons.

## 4. Что НЕ делаем

- Никакого fine-tuning (контекст-инъекция бьёт файнтюнинг для фактов/опыта).
- Никакого векторного RAG сейчас (объём памяти мал; точечные ключи quest_id/cell
  покрывают нужное). Вернёмся к эмбеддингам при тысячах записей.
- Никаких правок sim/bridge/game-source.

## 5. Риски

- Латентность: полный вызов 5–7с холодный / ~1с прогретый. Смягчение: вызовы только на
  переходах (should_consult), max_tokens=120, temperature=0, prompt-cache сервера.
- Модель может выбрать цель, противоречащую выживанию: policy-гейты (survival gate,
  hp-floor) остаются НЕОБХОДИМЫМ последним рубежом — brain предлагает, гейты запрещают.
- Windows/MSYS: запуск сервера через powershell-скрипт skill'а llama-launch (MAIN b10000).

## 6. Верификация (выполнено 2026-08-23, живой сервер :8081)

| Кейс | Ожидание | Факт |
|---|---|---|
| ACTIVE 6/10 + фейл accept в памяти | не ACCEPT | ✅ DO_OBJECTIVE |
| hp_frac=0.28 | HEAL | ✅ HEAL |
| READY 8/8, giver 4.2yd | TURN_IN | ✅ TURN_IN |
| json_schema strict + enum | валидный JSON | ✅ |

Латентность: floor ~1.9s (30 токенов), полный ~5–7s холодный, ~1–3s тёплый при t=0.

## 7. Acceptance

- A/B: прогон 3000 шагов WOC_BRAIN=off vs on. Критерии on: quests_turned_in > 0,
  меньше повторных фейлов одного типа на квест, смерти не хуже off.
- Юнит: llm_brain валидация enum/таймаута/офлайна (мок HTTP), should_consult правила,
  episodic writer читает старый файл (append-safe).
