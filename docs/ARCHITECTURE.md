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

### 2.1. Мост (browser_bridge_offline.cjs)

**Файл:** `D:\world-of-claudecraft\browser_bridge_offline.cjs`

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
  "in_combat": false
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
| `quest_objectives.cjs` | Статическая таблица квестов |

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
- `browser_bridge_offline.cjs`: accept/turn_in с навигацией к гиверу

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

## 6. Текущее состояние (2026-08-26)

**Коммиты:**
- `de871b2` — class config + offline bridge + plan-stack
- `5e40cf7` — merge с backup
- `efe0cb9` — hardened needs_tool invariant + replay persistence + quest lifecycle test
- `64ea6ad` — replay buffer serialization fix
- `6b4bc53` — sell_junk copper-delta verification
- `417834b` — plan-stack quest transaction
- `046b78c` — quality null + buy counter + schema contract test
- `1d4cceb` — canonical inventory schema + turn-in truth + stateful buy
- `fd99334` — inline QUEST_OBJECTIVES into readGameState
- `a744e3b` — buy distance check before sim.buyItem
- `f1ce454` — navigate to vendor + honest noTarget + itemId in verify
- `03f0cd7` — real vendor item names (handaxe/gathering_sickle)

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

**Итого тестов: 208 green** (было 91).

```
pytest test_loot_targets test_navigation test_autonomy_loop test_recovery_execution \
       test_planner test_quest_target test_autonomy_core test_observation_mask \
       test_skill_index_contract test_canonical_state test_evaluation test_replay_extended
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

## 9. Известные проблемы

| Проблема | Статус |
|----------|--------|
| Мост падает при background-запуске через Hermes | Обход: `start_offline.ps1` |
| Офлайн-мир ≠ онлайн (другие координаты) | Нормально для обучения |
| Персонаж level 1 (29 HP) спавнится рядом с мобами 382–1564 HP | Свойство world state, НЕ баг кода. Чинить кодом = оптимизировать под один плохой spawn |
| `entitiesNear` в живой игре `undefined` | Fallback к `sim.entities.values()` (Map, 985 сущностей) |
| `sim.interact()` безадресный | Для лута только `sim.lootCorpse(mobId, pid)` (`sim.ts:9727`) |
| headless env говорит низкоуровневыми действиями, контур — навыками | Нужен адаптер для P0.9 |

## 10. Что доказано и что нет

| Утверждение | Статус |
|---|---|
| Контур подключён, не падает | ✅ 208 тестов + живой прогон без traceback |
| Контракты навыков соответствуют игре | ✅ P0.1–P0.8 закрыты живым замером |
| Тредмилл (повтор без прогресса) сломан | ✅ было 153 холостых `loot`, стало 0 |
| Агент играет длинную дистанцию автономно | ❌ **не доказано** — нужен P0.9 baseline |
| Обучение УЛУЧШАЕТ политику | ❌ **не доказано** — нужен V0 → 100 ep → train → V1 → 100 НОВЫХ ep, `V1 > V0` |

**P1 без доказательства `V1 > V0` — это memorization, а не autonomy.**
PPO/self-learning (P2) начинать только после этого доказательства.
