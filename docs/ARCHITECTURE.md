# World of ClaudeCraft Agent — Architecture & State

> Этот файл — живой документ. Обновляется при каждом изменении.
> Дата последнего обновления: 2026-08-26

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

**Действия (idx):**
| idx | Действие | Описание |
|-----|----------|----------|
| 0 | farm | Атака ближайшего моба |
| 1 | loot | Поднять лут |
| 2 | accept_quest | Принять квест |
| 3 | turn_in_quest | Сдать квест |
| 4 | sell_junk | Продать мусор |
| 5 | gather | Добыть ресурс |
| 6 | craft | Крафт |
| 7 | heal | Лечение |
| 8 | equip | Экипировка |
| 9 | buy | Покупка |

**Снапшот (info):**
```json
{
  "player": {"hp": 100, "maxHp": 100, "level": 1, "dead": false},
  "player_pos": [x, z],
  "player_class": "warrior",
  "nearby": [...],
  "inventory": [...],
  "quests": {"active": [...], "done": [...]},
  "quests_done": 0,
  "kills": 0,
  "copper": 14,
  "in_combat": false
}
```

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

## 8. Следующие шаги

- [ ] Интеграция `cast_*` способностей в мост
- [ ] Полная поддержка warrior (melee) в policy
- [ ] Интеграция LLM как советника (WOC_BRAIN=advisory)
- [ ] Длинный прогон 1000+ шагов с метриками
