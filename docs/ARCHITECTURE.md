# World of ClaudeCraft Agent — Architecture & State

> Этот файл — живой документ. Обновляется при каждом изменении.
> Дата последнего обновления: 2026-08-27

## 1. Общая архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        World of ClaudeCraft                      │
│                     (игра, localhost:5173)                       │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │  Player  │  │   NPCs   │  │   Mobs   │  │  Gather Nodes  │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬────────┘  │
│       └──────────────┴─────────────┴────────────────┘            │
│                              │                                   │
│                    window.__game.sim                             │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  browser_bridge.cjs  │
                    │  (CDP :9222 → :8791) │
                    │  Puppeteer + HTTP    │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │    Python Agent      │
                    │  ┌────────────────┐  │
                    │  │  GoalManager   │  │
                    │  │  (FSM + Policy)│  │
                    │  └────────────────┘  │
                    │  ┌────────────────┐  │
                    │  │ ExperienceStore│  │
                    │  │  (Q-table +    │  │
                    │  │   replay buf)  │  │
                    │  └────────────────┘  │
                    │  ┌────────────────┐  │
                    │  │ SelfReflection │  │
                    │  │  (hints для    │  │
                    │  │   политики)    │  │
                    │  └────────────────┘  │
                    └─────────────────────┘
```

## 2. Компоненты

### 2.1. Мост (browser_bridge.cjs)

**Файл:** `D:\world-of-claudecraft\browser_bridge.cjs`

**Функции:**
- Подключение к Chrome через CDP (Chrome DevTools Protocol, порт 9222)
- Чтение `window.__game.sim` из игры
- Выполнение действий через `sim.*` и `controller.*`
- HTTP-сервер на порту 8791 для Python-агента

**API:**
- `GET /health` → `{ok, bridge, page, game}`
- `POST / {"action":"snapshot"}` → `{ok, info}`
- `POST / {"action":"step", "idx":N, "cmd":{}}` → `{ok, noTarget, info}`

**Действия — единственный источник истины `hierarchical_env.SKILLS` (13 навыков):**

| idx | Навык | Описание |
|-----|-------|----------|
| 0 | farm | Атака ближайшего моба |
| 1 | loot | Поднять лут — `sim.lootCorpse(mobId, pid)`, адресно |
| 2 | accept_quest | Принять квест |
| 3 | turn_in_quest | Сдать квест |
| 4 | sell_junk | Продать мусор |
| 5 | gather | Добыть ресурс |
| 6 | craft | Крафт |
| 7 | heal | Лечение |
| 8 | equip | Экипировка |
| 9 | buy | Покупка |
| 10 | cast_frostbolt | Спелл (mage) |
| 11 | cast_fireball | Спелл (mage) |
| 12 | craft_item | Крафт предмета |

**`respawn` — НЕ индекс, а отдельный endpoint:** `POST / {"action":"respawn"}`.
Выдумывать `SKILL_INDEX` нельзя: любой сдвиг (BUY→HEAL) портит весь replay.
Инвариант: `Python SKILLS == bridge action indices == actual handler dispatch`.

**Снапшот (info) — canonical-поля:**
```json
{
  "player": {"hp": 100, "maxHp": 100, "level": 1, "dead": false},
  "player_pos": [x, z],
  "player_class": "warrior",
  "nearby": [{"kind": "mob", "name": "...", "dist": 4.2, "maxHp": 42,
              "dead": false, "lootable": false, "templateId": "forest_wolf"}],
  "inventory_by_id": {"rough_hide": 2, "curved_tusk": 1},
  "equipment": {"mainHand": "rusty_axe"},
  "vendor_offers": [{"itemId": "handaxe", "price": 25}],
  "quests": {"active": [...], "done": [...]},
  "quests_done": 0,
  "kills": 0,
  "deaths": 0,
  "copper": 14,
  "in_combat": false,
  "quest_states": {"q_boars": "available", "q_bandits": "active"}
}
```

**Почему `inventory_by_id`, а не `free_slots`:** прогресс считается диффом
`{itemId: count}`. `free_slots` даёт ложный SUCCESS, когда один предмет
заменился другим.

### 2.2. Агент (python/)

**Файл:** `python/play_autonomous.py` — точка входа

**Ключевые модули:**

| Модуль | Назначение |
|--------|------------|
| `agent.py` | Главный цикл, связывает всё |
| `policy.py` | GoalManager — выбор действия |
| `world_state.py` | Построение WorldState из info |
| `memory.py` | ExperienceStore (Q-table + replay) |
| `self_reflection.py` | Анализ паттернов, генерация hints |
| `class_config.py` | Конфигурация классов (warrior/mage/hunter) |
| `game_agent_export.json` | Derived cache from `D:\woc-game` (generated) |
| `npc_registry.py` | Canonical NPC registry (P0-A) |
| `observation.py` | Кодирование состояния в obs (6 блоков) |
| `skill_contracts.py` | Контракты навыков (pre/postconditions) |
| `action_mask.py` | Фильтрация кандидатов по контрактам |
| `progress.py` | Детектор прогресса (дельты) |
| `recovery.py` | Лестница восстановления |
| `anti_loop.py` | LoopGuard — обнаружение циклов |
| `planner.py` | Планировщик подцелей (subgoals) |
| `navigation.py` | Навигация (nav_command, _nav_to) |
| `autonomy.py` | Автономный контур (AutonomyLoop) |

### 2.3. Классы персонажей

**Файл:** `python/class_config.py`

| Класс | Ресурс | Стиль | Основная атака | Дальность |
|-------|--------|-------|----------------|-----------|
| warrior | rage | melee | heroic_strike | 0-5 yd |
| mage | mana | ranged_kite | fireball | 0-30 yd |
| hunter | focus | ranged_kite | arcane_shot | 8-35 yd |

## 3. Квестовая система (Plan-Stack)

**Принцип:** квест = транзакция `[собрать] → [дойти] → [сдать]`

**Контракт:**
1. Неполный objective → `gather/farm` до полного
2. Все objectives полные → `return_to_giver` (навигация)
3. Гивер рядом (≤6 yd) → `turn_in_quest` (детерминированно)

**Фиксы:**
- `world_state.py`: `state="ready"` сервера = авторитетный READY
- `policy.py`: READY + гивер ≤6 yd → форсированный `turn_in_quest`
- `browser_bridge.cjs`: accept/turn_in с навигацией к гиверу

## 4. Экономический цикл

**Продажа:**
- `sell_junk` верифицируется copper-delta
- SUCCESS только если copper увеличился
- FAILURE → negative signal для Q-table

**Покупка:**
- `buy` с retry budget: 3 неудачи → cooldown 30 шагов
- Форсируется только при `needs_tool` и отсутствии инструмента в инвентаре

## 5. Самообучение

**Петля:**
```
игра → лог шага → SelfReflection.observe()
                    ↓ каждые 200 шагов
              reflect() → hints (spin/death/quest_stall)
                    ↓
              policy.load_reflection_hints()
                    ↓
              поведение изменилось → повтор
```

**Типы hints:**
- `spin:<action>` — действие удаляется из кандидатов
- `death:<cell>` — farm запрещён в клетке при hp<0.6
- `quest_stall` — приоритет квестов

## 6. Текущее состояние (2026-08-27)

**Коммиты:**
- `43fa139` — FIX #1-#4 для V1 readiness (quest_states, NpcRegistry priority, canonical key, GO_TO_GIVER)
- `e4b497b` — P0-A: NPC registry + target-aware quest planning
- `15dc2d2` — V0 browser 1000-step run — FROZEN
- `33b7134` — telemetry: record WHY each step failed

**Запуск:**
```powershell
powershell -File D:\world-of-claudecraft\start_offline.ps1
```

**Порты:**
- Игра: `localhost:5173` (Vite dev server)
- CDP: `9222` (Chrome DevTools)
- Мост: `8791` (HTTP API)

**Git:**
- Remote: `https://github.com/remontsuri/world-of-claudecraft-agent.git`
- Branch: `backup`

## 7. Известные проблемы

| Проблема | Статус |
|----------|--------|
| Мост падает при background-запуске через Hermes | Обход: `start_offline.ps1` |
| Агент не пишет в лог сразу | Нужно подождать 60-120с |
| Офлайн-мир ≠ онлайн (другие координаты) | Нормально для обучения |

## 8. Автономный контур (Plan 2026-08-26)

**План:** `docs/superpowers/plans/2026-08-26-autonomous-agent.md`

| # | Задача | Модуль | Тесты | Статус |
|---|--------|--------|-------|--------|
| 1 | Canonical World State | `world_state.py` | 16 | ✅ `7f76928` |
| 2 | Observation Encoder | `observation.py` | 12 | ✅ `b8b6986` |
| 3 | Skill Contracts | `skill_contracts.py` | 7 | ✅ `5b6b783` |
| 4 | Action Mask | `action_mask.py` | 10 | ✅ `b8b6986` |
| 5 | Progress Detector | `progress.py` | 7 | ✅ `5b6b783` |
| 6 | Recovery Manager | `recovery.py` | 5 | ✅ `5b6b783` |
| 7 | Anti-Loop System | `anti_loop.py` | 8 | ✅ `5b6b783` |
| 8 | Extended Replay | `replay.py` | ✔ | ✅ |
| 9 | Planner | `planner.py` | 26 | ✅ `d932963` |
| 10 | Evaluation Suite | `evaluation.py` | ✔ | ✅ |
| 11 | Wire into agent.py | `agent.py`, `play_autonomous.py` | ✔ | ✅ `1d0a5e498` |
| 12 | NPC Registry (P0-A) | `npc_registry.py` | 12 | ✅ `e4b497b` |
| 13 | FIX #1-#4 (V1 readiness) | `observation.py`, `npc_registry.py`, `snapshot.cjs` | 11 | ✅ `43fa139` |

**Итого тестов: 498 passed, 17 skipped** (было 208, стало 498).

```
pytest test_loot_targets test_navigation test_autonomy_loop test_recovery_execution \
       test_planner test_quest_target test_autonomy_core test_observation_mask \
       test_skill_index_contract test_canonical_state test_evaluation test_replay_extended \
       test_npc_registry test_fix1_quest_available test_fix4_giver_navigation
```

### 8.0. Аудит P0 — контрактные дефекты

Каждый пункт закрыт **живым замером**, не чтением кода.

| # | Дефект | Было | Стало | Коммит |
|---|--------|------|-------|--------|
| P0.1 | Прогресс инвентаря по `free_slots` | ложный SUCCESS при замене предмета | дифф `{itemId: count}` | `7c04995db` |
| P0.2 | `equipment_rev` не существует в игре | предикат всегда врал | дифф `{slot: itemId}` из снапшота | `7c04995db` |
| P0.3 | Неизвестный предикат → «разрешено» | контракт молча пропускал | `UnknownPredicate`, fail-closed | `7c04995db` |
| P0.4 | Цены выдуманы | `buy` уходил в отказ | 214 цен из `items.ts` → `item_prices.py` | `7c04995db` |
| P0.5 | `target = mobs[0]` | бил не квестового моба | `target = quest_mob` приоритетом | `1d0a5e498` |
| P0.6 | `policy._candidates` NameError | падение на шаге 0 | `player_class`/`class_cfg` выводятся | `1d0a5e498` |
| P0.7 | Контур писал `["skill"]`, политика читала `["hint"]` | контур считал шаги, поведение не менялось | `autonomy_subgoal` доходит | `1d0a5e498` |
| P0.8 | `loot` на декорациях | 153 подряд `inconclusive`, 0 прогресса | труп = `kind==mob` + dead/lootable + ≤12 yd | `ad1771d76` |
| P0.9 | long-horizon baseline | — | ⏳ в работе (headless) | — |

**Дополнительно закрыто тем же замером:**
- `heal` предлагался «always available» → 34 `failure` из 69. Теперь `_has_healing()`
  по паттерну `potion|tonic|elixir|bread|jerky|cooked|ration`.
- Два водителя: anchor тянул в `[-52,-4]`, контур — к мобу, взаимное гашение.
  Теперь anchor только наблюдает при активном `autonomy`.
- Suicidal combat: воин level 1 (29 HP) фармил Warlord Drogmar (1564 HP) → 55 смертей.
  Теперь `farm` не предлагается при `target.maxHp > player.maxHp * 3.0`.

### 8.05. Headless env — второй режим замера

**Файл:** `D:\woc-game\headless\env_server.ts` → `dist-env/env_server.cjs`
(сборка `npx esbuild headless/env_server.ts --bundle --platform=node --format=cjs`)

| | HEADLESS | BROWSER |
|---|---|---|
| Транспорт | NDJSON stdin/stdout | CDP → HTTP :8791 |
| Действия | **61 низкоуровневое** (`forward`, `attack`, `ability_N`) | **13 навыков** |
| Скорость | **296 шагов/сек** | ~0.1 шага/сек |
| Мир | clean seed, детерминизм | реальный offline-клиент |
| Отвечает на вопрос | «может ли архитектура играть при корректном старте?» | «справляется ли агент с конкретным состоянием клиента?» |

**Результаты этих режимов НЕ смешиваются.** Плохой spawn (level 1 рядом с
Warlord Drogmar 1564 HP) — свойство world state, а не код: чинить его кодом
значит оптимизировать агента под один плохой spawn.

**Протокол:**
```
{"cmd":"info"}                                    → obs_size=567, num_actions=61
{"cmd":"reset","seed":N,"player_class":"warrior"}  → {obs, info}
{"cmd":"step","action":N}                          → {obs, reward, terminated, truncated, info}
```

**Разрыв, который надо закрыть для P0.9:** headless принимает низкоуровневые
действия, а контур говорит навыками. Нужен адаптер `skill → [low-level actions]`
+ расширение `infoDict()` (сейчас отдаёт только 8 полей: `level, xp, hp, kills,
deaths, quests_done, copper, step` — нет objectives, skills-статистики,
economy, navigation, recovery, loops).

Reward-счётчики, доступные в `sim.counters`: `damageDealt, damageTaken, kills,
deaths, xpGained, questsCompleted, questProgress, levelUps`.

### 8.1. Контракты модулей

```
info (bridge snapshot)
  ↓ build_world_state()          world_state.py   — единственный источник истины
ws
  ↓ encode_observation(ws, info) observation.py   — 6 блоков для решения
obs
  ↓ plan_subgoals(obs)           planner.py       — objective → subgoals
subgoal
  ↓ mask_candidates(cands, obs)  action_mask.py   — выводится из контрактов
candidates
  ↓ policy.decide()              policy.py        — Q-table выбирает КАК
action
  ↓ bridge step                                    — исполнение
info_after
  ↓ detect_progress(before,after) progress.py     — дельты
progress
  ↓ verify_postconditions()      skill_contracts.py — SUCCESS/FAILURE/NO_OP
result
  ↓ get_recovery(reason)         recovery.py      — лестница восстановления
  ↓ LoopGuard.observe()          anti_loop.py     — цикл = повтор БЕЗ прогресса
```

### 8.2. Ключевые инварианты

- **Action mask выводится из `skill_contracts`** — нет второго набора правил, который разъедется.
- **`NO_OP` ≠ `SUCCESS`** — действие выполнилось, но мир не изменился, это не успех.
- **Цикл = повтор БЕЗ прогресса** — `farm × 20` с киллами это работа, а не цикл.
- **Инструмент покупается ДО выхода из города** — структурно в плане, а не в reward.
- **Имена инструментов из живой игры**: `handaxe`, `gathering_sickle`, `copper_mining_pick`. `logging_axe` / `herb_sack` в игре НЕ существуют (проверено тестом).
- **`min_dwell=20`** — цель не дёргается каждый шаг; `force` только на смерть/критический HP.
- **Лестница восстановления всегда заканчивается `abandon_objective`** — цикл не зависает.
- **Один writer у цели** — anchor выключается при активном `autonomy`, иначе два водителя гасят друг друга.
- **Неизвестный предикат = отказ, не разрешение** (`UnknownPredicate`, fail-closed).
- **Труп = мёртвый МОБ, не декорация.** Игровой флаг `lootable:true` стоит и на
  декорациях (`Ogre War Totem`, `Grave of Royal Assassin Voss`, `Warded Shore-Rock`).
  Предикат `kind==mob && (dead||lootable) && dist<=12` продублирован в
  `policy` / `navigation` / `observation` / `world_state` — фикс одного слоя цикл не лечит.
- **`heal` требует, чтобы было чем лечиться** — иначе 34 `failure` подряд.
- **Цены только из `woc-game/src/sim/content/items.ts`** (`buyValue`), 214 предметов.
  `sim.itemDef` не экспонирован — выдумывать цены нельзя.
- **Правила игры читаются из `src/sim/`, не угадываются.**
- **`quest_available` = существует гивер AND `questState(questId) == 'available'`** (FIX #1).
  `sim.questState()` — авторитетный метод в offline (проверен 2026-08-27).
- **NpcRegistry source priority:** `runtime_entity > world_content > snapshot > memory` (FIX #2).
  `update_from_*` не перезаписывает более приоритетный источник.
- **NpcRegistry canonical key:** `npc_id` (строковый) отдельный от `entity_id` (числовой) и `template_id` (FIX #3).
- **`GO_TO_GIVER` — navigation hint, не policy skill** (FIX #4).
  Planner возвращает `skill="explore"` для навигации. Autonomy обрабатывает через `_nav_to()` → `nav_command`.
  `explore` — валидный навык (пустые предусловия, в `ALWAYS_AVAILABLE`).

### 8.3. P0-A: Canonical NPC Registry (npc_registry.py)

**Файл:** `python/npc_registry.py`

**Источники (по приоритету):**
1. `runtime_entity` (sim.entities) — высший приоритет позиции
2. `world_content` (worldContent.npcs) — статический контент
3. `snapshot` (bridge nearby) — live данные из моста
4. `memory` (WorldMemory) — persisted knowledge, низший приоритет

**Контракт:**
- Ключ реестра = `npc_id` (строковый, из worldContent или templateId)
- `entity_id` = числовой id из runtime (для bridge actions)
- `template_id` = строковый templateId (для сопоставления с quest.giverNpcId)

**Методы:**
- `update_from_world_content(npcs)` — статический контент
- `update_from_runtime_entities(entities)` — runtime entities
- `update_from_snapshot(nearby)` — live bridge data
- `update_from_memory(memory)` — WorldMemory
- `find_giver_for_quest(quest_id)` — найти гивера по quest_id
- `get_npc_position(npc_id)` — позиция NPC
- `get_giver_position_for_quest(quest_id)` — позиция гивера для квеста

### 8.4. FIX #1-#4 (V1 readiness, коммит `43fa139`)

**FIX #1: `quest_available` через `sim.questState()`**
- Раньше: `bool(givers)` = "NPC имеет questIds" (ложно при done/active/unavailable)
- Теперь: `exists giver AND questState == 'available'`
- `snapshot.cjs` собирает `quest_states` из `sim.questState()` для всех NPC
- `observation.py`: `_quest_available_from_states(ws, givers)`

**FIX #2: NpcRegistry source priority contract**
- Раньше: `update_from_snapshot` безусловно перезаписывал позицию
- Теперь: `_should_update_position()` через `SOURCE_PRIORITY`

**FIX #3: Canonical npc_id отдельный от entity_id/template_id**
- Раньше: ключ = `templateId or id` (числовой entity.id ломал поиск)
- Теперь: ключ = `npc_id` (строковый), `entity_id` сохранён отдельно

**FIX #4: `GO_TO_GIVER` — navigation hint, не unknown_skill**
- Planner возвращает `skill="explore"` для навигации
- Autonomy обрабатывает через `_nav_to()` → `nav_command` + `forced="explore"`
- `explore` — валидный навык (пустые предусловия, в `ALWAYS_AVAILABLE`)

**Регрессионные тесты:**
- `test_fix1_quest_available.py`: 7 тестов (iron invariant: 11 givers + 0 available → 0 accept)
- `test_fix4_giver_navigation.py`: 4 теста (GO_TO_GIVER → nav_command, не unknown_skill)
- `test_npc_registry.py`: 12 тестов (priority + canonical key contracts)

### 8.5. Loop Fix: accept_quest mask синхронизирован с quest_states (коммит `b731ee0`)

**Проблема:** агент зацикливался на `accept_quest -> INCONCLUSIVE` (70+ шагов) в зонах без доступных квестов.

**Причина:**
- `hierarchical_env.action_masks()` разрешал `accept_quest` по `bool(quest_npcs)` (NPC имеет questIds)
- `policy._candidates()` добавлял `accept_quest` по `has_new_quest_nearby` (questId не в логе)
- `skill_contracts.check_preconditions('accept_quest')` блокировал по `quest_available=False`
- Результат: маска разрешает → политика выбирает → предусловия отбивают → INCONCLUSIVE → повтор

**Исправление:**
- `hierarchical_env.py`: `mask[2] = has_available_quest` (проверяет `quest_states[questId] == 'available'`)
- `policy.py`: `has_new_quest_nearby` учитывает `quest_states.get(qid) == 'available'`
- Тесты обновлены для передачи `quest_states` в `info`

## 9. Известные проблемы

| Проблема | Статус |
|----------|--------|
| Мост падает при background-запуске через Hermes | Обход: `start_offline.ps1` |
| Loop Fix: accept_quest mask синхронизирован с quest_states | ✅ `b731ee0` |
| Офлайн-мир ≠ онлайн (другие координаты) | Нормально для обучения |
| Персонаж level 1 (29 HP) спавнится рядом с мобами 382–1564 HP | Свойство world state, НЕ баг кода. Чинить кодом = оптимизировать под один плохой spawn |
| `entitiesNear` в живой игре `undefined` | Fallback к `sim.entities.values()` (Map, 985 сущностей) |
| `sim.interact()` безадресный | Для лута только `sim.lootCorpse(mobId, pid)` (`sim.ts:9727`) |
| headless env говорит низкоуровневыми действиями, контур — навыками | Нужен адаптер для P0.9 |

## 10. Что доказано и что нет

| Утверждение | Статус |
|---|---|
| Контур подключён, не падает | ✅ 498 тестов + живой прогон без traceback |
| Контракты навыков соответствуют игре | ✅ P0.1–P0.8 закрыты живым замером |
| Тредмилл (повтор без прогресса) сломан | ✅ было 153 холостых `loot`, стало 0 |
| NPC Registry с правильным priority и canonical key | ✅ FIX #2 + FIX #3, 12 тестов |
| `quest_available` через `sim.questState()` | ✅ FIX #1, 7 тестов (iron invariant) |
| `GO_TO_GIVER` → nav_command, не unknown_skill | ✅ FIX #4, 4 теста |
| Агент играет длинную дистанцию автономно | ❌ **не доказано** — нужен P0.9 baseline |
| Обучение УЛУЧШАЕТ политику | ❌ **не доказано** — нужен V0 → 100 ep → train → V1 → 100 НОВЫХ ep, `V1 > V0` |

**P1 без доказательства `V1 > V0` — это memorization, а не autonomy.**
PPO/self-learning (P2) начинать только после этого доказательства.

## 11. V0 Baseline (FROZEN)

**Коммит:** `15dc2d2b9`
**Отчёт:** `docs/baselines/V0-browser-2026-08-27.md`
**Статус:** FROZEN — не изменять после начала фиксов.

**Результат:** 989/1000 шагов, `autonomy_errors=0`.
- `accept_quest` 964/989 = 97.5%, все NO_OP
- До шага 35: `accept → farm×8 → return_to_giver → turn_in_quest` РАБОТАЕТ
- Quest сдан на шаге 35
- `recoveries=986, recoveries_executed=8, loops_tripped=752, max_no_progress_run=964`
- AutonomyScore = **30.2%**

**Root cause:** `snapshot.cjs:315` читает только `g.online.questsDone`. В offline
`g.online === false` → `undefined` → fallback `done.length=0` → постусловие
`quests_done_increased` никогда не выполняется в offline.

## 12. Архитектурная граница (зафиксирована 2026-08-27)

| Репозиторий | Ответственность |
|-------------|-----------------|
| **GAME REPO** (`levy-street/world-of-claudecraft`) | АБСОЛЮТНАЯ ИСТИНА о мире и правилах (sim, entities, content, quest engine, combat, economy, navigation, Capability API) |
| **AGENT REPO** (`remontsuri/world-of-claudecraft-agent`) | АБСОЛЮТНАЯ ИСТИНА о принятии решений и обучении (Planner, PPO, Q-learning, Recovery, LoopGuard, Memory, Evaluation) |
| **BRIDGE** | Только транспорт между ними |

**Принцип:** Agent repo НЕ дублирует game data. Основная игра уже умеет
правильно вычислять `questState()` через `computeQuestState()`. Agent repo
должен только выбирать цель, идти, переключаться, учить.
