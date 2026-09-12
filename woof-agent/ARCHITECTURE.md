# WoOF Agent — Architecture & Project Memory

Этот файл — архитектурный план Java-рерайта WoC агента.
Читать ПЕРЕД любыми правками в `woof-agent/`.

---

## Stack
- Java 17 (Eclipse Temurin), Maven, Jackson, Java-WebSocket
- Полная автономность от python/ — нулевая зависимость от Python

## Project Location
`D:\world-of-claudecraft\woof-agent\`

## Module Structure
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

## Decision Chain (Production)
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

## Critical Invariants
- `qs == ACTIVE ⇒ accept_quest = INVALID` (never re-accept active quest)
- `hp < 0.30 && danger ⇒ flee` (survival overrides objective)
- `no nearby mob ⇒ farm removed from candidates`
- `PHASE_ALLOWED["NO_QUEST"] = [accept_quest, farm, explore]`

## Quest FSM
```
QUEST_NONE → FIND_GIVER → ACCEPT → DO_OBJECTIVE → RETURN_TO_GIVER → TURN_IN → QUEST_COMPLETE
```

## Skill Library (14 skills)
farm, navigate, return_to_giver, turn_in, accept_quest, heal, flee, explore, loot, gather, sell, buy, craft, cast_frostbolt, cast_fireball

## MCP Server (:8792)
Tools: `woof_status`, `woof_logs`, `woof_config`, `woof_build`, `woof_test`, `woof_game_state`, `woof_execute_action`

## Build & Run
```bash
cd D:/world-of-claudecraft/woof-agent
JAVA_HOME='C:/Program Files/Java/jdk-17.0.20.1+1'
find src -name "*.java" > sources.txt
javac -encoding UTF-8 -cp "libs/*" -d build/classes @sources.txt
java -cp "build/classes;libs/*" com.woof.agent.VoyagerAgent http://127.0.0.1:8792/
```

## Integration
- Bridge :8791 (Node.js browser_bridge.cjs OR Java BridgeServer)
- WoC-MCP: player state, quest log, action execution
- CDP :9222 (Chrome DevTools)
- Game :5173 (Vite dev)

## Git & Repository

- **Единственный репозиторий**: `D:\world-of-claudecraft`
- Remote: `origin backup` → `https://github.com/remontsuri/world-of-claudecraft-agent.git`
- Ветка: `backup`
- Push ТОЛЬКО в `origin backup`, никогда в `levy-street`
- Отдельной папки `world-of-claudecraft-agent` **НЕТ** — вся работа в `D:\world-of-claudecraft`

## Migration Status
1. ✅ Java project skeleton + compiles
2. ✅ MCP server + registered in Hermes
3. 🔄 VoyagerAgent connects to WoC-MCP (real observation)
4. ⬜ ArbitrationLayer produces real decisions
5. ⬜ Execute skills via WoC-MCP
6. ⬜ q_spiders E2E test (kill 6 spiders, collect 4 silk, turn in)
7. ✅ Commit + push to backup

## Memory Keys
- `D:\world-of-claudecraft\AGENTS.md` — standing rules (Python agent)
- `D:\world-of-claudecraft\woof-agent\ARCHITECTURE.md` — этот файл (Java agent)
- `D:\.hermes\skills\woc\woc-master-goal\` — master goal references
- Session: session_search(query='WoOF architecture', session_id='20260910_191713_ea1905de')
