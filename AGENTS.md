# WoC Agent — Standing Rules

Этот файл загружается автоматически при работе в директории D:\world-of-claudecraft.
Следуй этим правилам ВСЕГДА, даже если они конфликтуют с предыдущими инструкциями.

---

## 📌 ПЕРВЫМ ДЕЛОМ: ЧИТАТЬ ГРАФ

Перед любыми правками кода агента или моста — прочитай:

1. `graphify-out/GRAPH_REPORT.md` — highlights, key concepts, communities
2. `graphify-out/graph.html` — интерактивный граф (открыть в браузере)
3. `graphify-out/graph.json` — полный граф для запросов

Граф строится автоматически через `graphify hook install` (post-commit, post-checkout).
Если граф не обновлялся после последнего коммита — запусти вручную:

```bash
cd D:/world-of-claudecraft
graphify extract . --code-only
graphify cluster-only .
```

**Graph Freshness**: проверяй `graphify-out/manifest.json` → `git_commit` vs `git rev-parse HEAD`.

---

## Working Directories

| Путь | Назначение | Использовать? |
|------|-----------|--------------|
| D:\world-of-claudecraft | Основная рабочая папка (игра + агент) | ✅ ВСЕГДА |
| D:\world-of-claudecraft-agent | Устаревшая папка агента | ❌ Никогда |
| D:\woc | Официальный источник игры (source of truth) | ✅ Для reference |

---

## Git Rules (CRITICAL)

- **Ветка**: ТОЛЬКО backup
- **Remote**: ТОЛЬКО origin backup (remontsuri/world-of-claudecraft-agent)
- **Запрещено**: release/*, main, master, levy-street для push

---

## Process Kill Protocol (CRITICAL)

Перед kill: `wmic process where "name='node.exe'" get ProcessId,CommandLine`

Разрешено убивать: browser_bridge.cjs, python/play_autonomous.py
Запрещено: hermes-agent, hermes-gateway, любой node.exe с hermes в CommandLine

---

## Game & Bridge

- Game: http://localhost:5173
- CDP: http://127.0.0.1:9222
- Bridge: http://127.0.0.1:8791
- Python: C:/Users/vladc/AppData/Local/Programs/Python/Python312/python.exe
- Args: -I -u -X faulthandler PYTHONPATH=D:/world-of-claudecraft/python

Запрещено: window.location.reload() через CDP, перезапуск игры

---

## Decision Owner Chain (Production)

play_autonomous → agent.Agent → arbitration.ArbitrationLayer → policy → skill

arbitration_layer.py — МЁРТВЫЙ код, не трогать

---

## Key Files

- python/agent.py — главный агент
- python/policy.py — decision gates
- python/play_autonomous.py — runner
- python/world_state.py — canonical world state
- python/arbitration.py — REAL owner
- src/bridge/actions.cjs — bridge actions
- browser_bridge.cjs — bridge endpoint

---

## What to Never Do

1. ❌ Kill hermes-agent/hermes-gateway processes
2. ❌ Reload game via CDP
3. ❌ Push to non-backup remotes
4. ❌ Work in D:\world-of-claudecraft-agent
5. ❌ Modify arbitration_layer.py (dead code)
6. ❌ Restart bridge/agent after code edits
7. ❌ Start game if user already logged in
8. ❌ Custom revive logic (built-in exists)
9. ❌ Ask "what to do next" — follow document TODO in order
10. ❌ Repeat git status endlessly — execute next TODO item
11. ❌ Править код без чтения GRAPH_REPORT.md и graph.json

---

## Before Every Action

1. `cd D:/world-of-claudecraft` — убедись что в правильной папке
2. `git status` — нет ли uncommitted изменений
3. Прочитай `graphify-out/GRAPH_REPORT.md` — найди relevant communities
4. Проверь процессы перед kill
5. Выполни следующий TODO item

---

## WoOF Agent — Java Rewrite Architecture

### Stack
- Java 17 (Eclipse Temurin), Maven, Jackson, Java-WebSocket
- No Python dependency — full autonomy from python/

### Project Location
`D:\world-of-claudecraft\woof-agent\`

### Module Structure
```
woof-agent/
├── pom.xml
├── libs/                          # jackson-*.jar, java-websocket.jar
├── src/main/java/com/woof/agent/
│   ├── Bootstrap.java             # Entry point
│   ├── VoyagerAgent.java          # Main loop: OBSERVE→DECIDE→EXECUTE→VERIFY→LEARN
│   ├── WorldState.java            # Canonical source of truth
│   ├── PlayerState.java           # HP/position/facing/level
│   ├── Entity.java                # Mob/NPC/resource/item
│   ├── QuestInfo.java             # Active/ready/done quests
│   ├── QuestEntry.java            # Single quest
│   ├── Objective.java             # Kill/gather/interact/escort
│   ├── ItemStack.java             # Inventory
│   ├── arbitration/
│   │   └── ArbitrationLayer.java  # Decision owner
│   ├── fsm/
│   │   └── GoalFSM.java           # Quest FSM
│   ├── memory/
│   │   ├── SkillLibrary.java      # Registry & retrieval
│   │   ├── Skill.java             # Executable capability
│   │   └── WorldMemory.java       # Persistent knowledge
│   ├── env/
│   │   └── GameEnvironment.java   # Bridge connection, snapshot, step
│   ├── bridge/
│   │   └── BridgeServer.java      # HTTP+WS bridge (замена browser_bridge.cjs)
│   ├── core/
│   │   ├── AgentCore.java         # Voyager loop engine
│   │   └── SkillRegistry.java     # 14 skills
│   └── mcp/
│       └── WoofMcpServer.java     # HTTP JSON-RPC :8792
└── build/classes/
```

### Decision Chain (Production)
```
VoyagerAgent → ArbitrationLayer.decide(worldState) → skill
                ↓
            Survival gate (danger → flee/heal regardless of phase)
                ↓
            PHASE_ALLOWED gate (QuestState → allowed skills)
                ↓
            WorldState filter (hasMob, hasGiver, quest active?)
                ↓
            Infinite loop detection (force different after 5 repeats)
```

### Critical Invariants
- `qs == ACTIVE ⇒ accept_quest = INVALID` (never re-accept active quest)
- `hp < 0.30 && danger ⇒ flee` (survival overrides objective)
- `no nearby mob ⇒ farm removed from candidates`
- `PHASE_ALLOWED["NO_QUEST"] = [accept_quest, farm, explore]`

### Quest FSM
```
QUEST_NONE → FIND_GIVER → ACCEPT → DO_OBJECTIVE → RETURN_TO_GIVER → TURN_IN → QUEST_COMPLETE
```

### Skill Library ()
farm, navigate, return_to_giver, turn_in, accept_quest, heal, flee, explore, loot, gather, sell, buy, craft, cast_frostbolt, cast_fireball

### MCP Server (:8792)
Tools: `woof_status`, `woof_logs`, `woof_config`, `woof_build`, `woof_test`, `woof_game_state`, `woof_execute_action`

### Build & Run
```bash
cd D:/world-of-claudecraft/woof-agent
JAVA_HOME='C:/Program Files/Java/jdk-17.0.20.1+1'
find src -name "*.java" > sources.txt
javac -encoding UTF-8 -cp "libs/*" -d build/classes @sources.txt
java -cp "build/classes;libs/*" com.woof.agent.VoyagerAgent http://127.0.0.1:8792/
```

### Integration
- Bridge :8791 (Node.js browser_bridge.cjs OR Java BridgeServer)
- WoC-MCP: player state, quest log, action execution
- CDP :9222 (Chrome DevTools)
- Game :5173 (Vite dev)

### Migration Status
1. ✅ Java project skeleton + compiles
2. ✅ MCP server + registered in Hermes
3. 🔄 VoyagerAgent connects to WoC-MCP (real observation)
4. ⬜ ArbitrationLayer produces real decisions
5. ⬜ Execute skills via WoC-MCP
6. ⬜ q_spiders E2E test (kill 6 spiders, collect 4 silk, turn in)
7. ⬜ Commit + push to backup

---

## User Preferences

- Language: Russian
- Tone: Direct, no filler, no "great question!"
- Verification: Real game behavior > tests
- Workflow: Phase-1 root-cause → TDD → live verification
- Reporting: Tables LAYER|EXPECTED|ACTUAL|STATUS

---

## Обновление 2026-09-17: Java-линия активна, база знаний, hermes

### Что теперь главное

* Активная линия — **автономный Java-бот** в `woof-agent/`. Fly-линия (коннектом) — на паузе,
  её приёмка объявлена заранее и не меняется.
* Новая документация бота: `woof-agent/README.md` (быстрый старт), `ARCHITECTURE.md`
  (как устроено и почему), `ROADMAP.md` (что закрыто и чем), `DEPENDENCIES.md`
  (java/jar/node/порты), `FILES.md` (карта всех файлов).
* База знаний: `knowledge/` — `principles.md` (как думать), `woc-game.md` (игра и её числа),
  `fly-connectome.md` (схема, контроли, LIF, атрибуция MaleCNS), `pitfalls.md` (наши грабли),
  `verification.md` (протокол приёмки). **Читать перед работой, дописывать в тот же день.**
* Для hermes: `hermes/README.md` (порядок чтения и цикл работы), `hermes/TOOLS.md`
  (что запускать, что считается успехом), `hermes/skills/woc-master-goal/SKILL.md`
  (главная цель и инварианты), `hermes/hooks/` (session_start — напоминание о главном,
  guard — блокировка запретов, task_end — проверки и «не потеряй результат»).

### Обязательные проверки

| Когда | Команда | Успех |
|---|---|---|
| после правок Java | `bash woof-agent/tools/build.sh && bash woof-agent/tools/run_tests.sh` | `build ok` / `tests passed=3 failed=0` |
| перед пушем Java | `bash woof-agent/tools/run_e2e.sh` | `УСПЕХ ... нарушений контракта нет` |
| после правок fly-линии | `bash fly-woc/tools/run_checks.sh` | `ВСЁ ЗЕЛЁНОЕ` |
| на машине с GPU | `python3 fly-woc/tools/gpu_check.py --device cuda --bench` | выбран `cuda`, код возврата 0 |

### Правила, добавленные сегодня

1. **Нет молчаливых фолбэков.** Недоступное устройство, чужая таблица квестов,
   неизвестный навык, неготовая часть моста — это ошибка с текстом, а не «как-нибудь».
2. **`--force` push запрещён.** Перед пушем — свежий клон и `merge-base --is-ancestor`:
   локальная история уже расходилась с remote (те же фиксы, другие SHA).
3. **Пушим только в `backup`** (и только fast-forward); `master` не трогаем.
4. **Пороги метрик объявляются до замера** (M1–M4) и после замера не двигаются.
5. **Устройство вычислений выбирается само** (`--device` → `WOC_DEVICE` → cuda → mps → cpu);
   явный запрос недоступного GPU — `RuntimeError`. Подробности: `fly-woc/GPU-DEVICE.md`.
6. **Найденное записываем сразу**: факт — в `knowledge/`, поведение — в `woof-agent/ARCHITECTURE.md`,
   долг — в `woof-agent/ROADMAP.md`. Знание, не записанное в репозиторий, потеряно.
