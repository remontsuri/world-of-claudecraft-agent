# Спека: 6-уровневая архитектура автономного агента (утверждена пользователем)

Дата: 2026-08-24. Автор структуры: пользователь. Реализация: парная
(ведущий архитектор + со-архитектор `tencent/hy3:free` через `nous`).

## Целевая структура

```
QWEN / META POLICY        стратегия раз в 20-100 шагов, не джойстик
        ↓
GOAL MANAGER              ОДНА активная цель, конфликтующие действия запрещены
        ↓
PLANNER                   цель → цепочка подшагов (ACCEPT→KILL→RETURN→TURN_IN)
        ↓
SKILL POLICY              combat / navigation / quest / heal / loot
        ↓
CONTROLLER                move / face / interact / attack
        ↓
BRIDGE                    ТОЛЬКО факты: snapshot + events + RPC
        ↓
GAME
```

Сбоку — контур обучения:
```
World → Event → Reward → Replay(приоритетный) → Q/Policy →
Strategy Memory → Reflection / Failure Analysis → улучшение Goal/Planner
```

## Обязательные принципы (из ТЗ пользователя)

1. **Bridge не содержит интеллекта.** Он источник фактов; решения выше.
2. **VERIFY на каждом переходе.** `ok:true` от RPC — НЕ доказательство.
   Доказательство — изменение мира (`quest.active == true`, `quests_done += 1`).
3. **Один Python-процесс живёт весь прогон.** Никаких перезапусков между
   фазами; одна история, одна модель мира, одна память.
4. **Награда привязана к событиям**, а не к догадкам по снапшоту.
5. **LLM — стратег**, ему на вход состояние, на выход
   `{goal, strategy, priority}`; никаких «нажми attack».

## Этап 1 (реализуем сейчас, в этом порядке)

| # | Слой | Суть | Приёмка |
|---|---|---|---|
| 1 | **Quest Truth Layer** | абсолютная истина о квестах: id, phase, accepted, progress/required, giver_id, giver_pos, distance. Единственный источник, все остальные читают его | юнит-тесты фаз; `accept` физически невозможен для ACTIVE квеста |
| 2 | **Event Bus** | `QuestAccepted`, `ObjectiveProgress(old,new)`, `QuestCompleted`, `DamageTaken`, `PlayerDied`, `PlayerRespawned`, `ItemLooted`, `InventoryFull`, `NavigationStuck` | события пишутся в jsonl; на прогоне ≥1 событие каждого достижимого типа |
| 3 | **Goal Manager (lifecycle)** | NO_GOAL→FIND_QUEST→ACCEPT→VERIFY_ACCEPTED→COMPLETE_OBJECTIVE→VERIFY_OBJECTIVE→RETURN→VERIFY_AT_GIVER→TURN_IN→VERIFY_COMPLETION→REWARD→NEXT | `goal_switches / шаг` < 0.05 (сейчас 0.71!) |
| 4 | **Planner** | цель → явная цепочка подшагов с текущим индексом | план виден в логе; шаг не меняется, пока подшаг не верифицирован |
| 5 | **Failure Analyzer** | классы: ENVIRONMENT / NAVIGATION / COMBAT / QUEST / INTERACTION / SURVIVAL / PLANNING | каждый FAILURE в логе имеет класс |
| 6 | **Prioritized Replay** | приоритеты: explore 1, move 1, loot 2, damage 3, death 5, quest_accepted 8, objective_progress 10, quest_completed 20 | редкие события не вытесняются рутиной |
| 7 | **Strategy Memory** | per-quest: success/failure счётчики + лучшая стратегия (порог хила, дистанция боя) | стратегия читается перед планированием |
| 8 | **Qwen как стратег** | только после 1-7 | `{goal, strategy, priority}` в enum-контракте |

## Уже сделано из общей картины (до этой спеки)

- Bridge как источник фактов: `snapshot` / `step` / `navigate` / `raw_move`.
- Честные верификаторы по дельте мира (`verifiers_py.py`), включая тихие
  отказы сервера при turn-in.
- `noTarget` → `failure` для gather (действие без объекта = провал решения).
- Гибридный гейт gather (объект рядом + редкая разведочная проба).
- spin-хинты подавляют вес, а не вырезают скилл (`SPIN_WEIGHT_MULT`).
- Домашний якорь рабочей зоны (`work_anchor.py`).
- **Анти-рыскание камеры** (`heading.cjs`, гистерезис 0.35/0.10 рад) — баг,
  замеченный пользователем: агент дёргал камеру каждый тик.
- Эпизодическая память попыток (`episodic.py`).

## Измеренная точка отсчёта (прогон 3000 шагов, до этапа 1)

```
kills 797 | deaths 853 | quests_turned_in 0 | quests_completed 0
goal_switches 2141 (0.71 на шаг!)  repeated_mistakes 700 (23%)
heal 1.4% (было 22-31%)  gather 0.8% пустых (было 14.6%)
death/100 в последнем окне 0.20 => 2.0/1000 (на границе приёмки)
```

Главный провал — `quests_turned_in = 0` и `goal_switches = 0.71/шаг`:
цель переписывается почти каждый шаг, поэтому многошаговая доставка к
гиверу физически не доживает до конца. Это ровно то, что лечит
Goal Manager с VERIFY-переходами (пункт 3).
