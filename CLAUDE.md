# CLAUDE.md — World of ClaudeCraft Agent

## Репозитории

| Роль | Путь | GitHub |
|------|------|--------|
| **Game (upstream/истина)** | `D:/woc-game/` | `levy-street/world-of-claudecraft` |
| **Agent (consumer)** | `D:/world-of-claudecraft/` | `remontsuri/world-of-claudecraft-agent` |

## Архитектура

```
OFFLINE GAME (D:/woc-game/src/sim/, worldContent/)
    │
    ├── sim.questLog, sim.entities, sim.player
    ├── worldContent.npcs, quest definitions
    └── g.online.questsDone, sim.questState()
          │
          ▼
     browser_bridge.cjs (D:/world-of-claudecraft/src/bridge/)
          │
          ├── snapshot.cjs — извлекает из window.__game
          ├── actions.cjs — выполняет действия
          └── HTTP :8791
               │
               ▼
          canonical WorldState (python/world_state.py)
               │
               ▼
          observation.py → policy → planner → skills → autonomy
```

## Source of Truth

**GAME REPO = истина о мире.**
**AGENT REPO = consumer/controller/learner.**

НЕ дублировать:
- quest definitions
- NPC definitions
- item definitions
- coordinates
- combat mechanics
- interaction range

Перед реализацией — проверить `src/sim/`, `src/data/`, `worldContent/`, `sim.questState()`, `sim.entities`.

## Canonical Schema

| Поле | Тип | Источник |
|------|-----|----------|
| item ID | `itemId` (не `id`) | `slot.itemId` |
| inventory | `inventory_by_id` (единый) | `invFull.reduce(...)` |
| quality | `string` ("poor"/"common"/...) | `slot.quality` |
| quests_done | `Set.size` или `length` | `g.online.questsDone` |
| quest required | `qp.resolvedCounts[i]` | НЕ `qp.counts[i]` |
| NPC positions | live `sim.entities` | НЕ статические таблицы |
| turn-in NPC | `QUEST_GIVERS[qid]` from `game_agent_export.json` | generated from `D:\woc-game` |
| vendor | `kind==='npc' && vendorItems.length>0` | `nearby[].vendor` |

## Offline Entry Flow

```
http://localhost:5173/
    ↓
#btn-offline (hidden hook, fire .click())
    ↓
#offline-select .mini-class[data-class="warrior"]
    ↓
#char-name = "TestHero" (обязательно!)
    ↓
#btn-start-offline
    ↓
wait window.__game.sim.player
```

## Startup Procedure

```bash
# 1. Запустить vite ИЗ ИГРЫ
powershell.exe -Command "Stop-Process -Id (Get-NetTCPConnection -LocalPort 5173 -State Listen).OwningProcess -Force" 2>/dev/null
cd D:/woc-game && node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173

# 2. Запустить bridge (из агента)
cd D:/world-of-claudecraft && node browser_bridge.cjs

# 3. Запустить offline flow (через CDP или enter_offline_game.mjs)

# 4. Проверить
curl -s http://127.0.0.1:8791/health
# {"ok":true,"bridge":true,"page":true,"game":true}
```

## Test Commands

```bash
# pytest
cd D:/world-of-claudecraft/python && python -m pytest test_*.py -x --tb=short

# bridge tests
cd D:/world-of-claudecraft && node src/bridge/test_bridge.cjs

# live snapshot
curl -s -X POST http://127.0.0.1:8791 -H "Content-Type: application/json" -d '{"action":"snapshot"}' | python3 -m json.tool
```

## Forbidden Assumptions

- ❌ `sim.questDefs` всегда доступен → использовать `sim.questLog`
- ❌ `g.online === true` в offline → `g.online === false`
- ❌ `quests.done` число → это `Set`
- ❌ `quality` число → строка
- ❌ `id` в inventory → `itemId`
- ❌ статические NPC позиции → live `sim.entities`
- ❌ `qp.counts[i]` = required → это текущий прогресс, required = `qp.resolvedCounts[i]`

## Commit/Push Rules

- Конкретные файлы, не всё подряд
- Conventional Commits: `fix:`, `feat:`, `refactor:`, `chore:`
- Не пушить в `levy-street/world-of-claudecraft` без прав

## Skills

Используй при необходимости:
- `repo-audit` — полный аудит репозиториев
- `cross-repo-contract-audit` — аудит полей между слоями
- `browser-cdp-debug` — диагностика CDP
- `live-probe` — живой замер гипотез
- `regression-engineer` — фикс через regression
- `game-source-of-truth` — проверка наличия API в игре
