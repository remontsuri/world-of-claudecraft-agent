# Карта файлов woof-agent

Сгенерировано из кода (`tools/` скрипты, `src/` классы, `tests/` проверки).
Правило: назначение класса берётся из его же doc-комментария, а не из чужих слов.

## src/main/java/com/woof/agent (28 классов)

| Файл | Назначение | Строк |
|---|---|---|
| `Bootstrap.java` | Bootstrap — полный старт агента. Раньше здесь создавался BridgeServer с зашитым GUID вкладки CDP и GameEnvironment-заглушка, поэтому «Bootstrap» не мо | 16 |
| `VoyagerAgent.java` | VoyagerAgent — точка входа автономного агента. Запуск:  java -cp "build/classes:libs/*" com.woof.agent.VoyagerAgent [--steps N] [--bridge URL] Мост по | 75 |
| `arbitration/ArbitrationLayer.java` | ArbitrationLayer — решает, какой навык выполнять. Гейты фаз, спасение при опасности, защита от бесконечного цикла. Порядок приоритетов (был сломан: re | 181 |
| `bridge/BridgeMain.java` | BridgeMain — запуск Java-моста на :8791. --upstream URL  мост Java впереди, Node за ним (рабочий вариант сейчас) без --upstream   чистый CDP-мост (тра | 28 |
| `bridge/BridgeServer.java` | BridgeServer — HTTP-мост на Java, тот же контракт, что у browser_bridge.cjs: POST / {"action":"snapshot"|"step"|"navigate"|"raw_move"|"respawn"|"explo | 96 |
| `bridge/CdpBackend.java` | CdpBackend — мост, который сам говорит с Chrome DevTools Protocol (замена browser_bridge.cjs целиком, без Node-прослойки). Состояние: транспорт уже ес | 37 |
| `bridge/CdpClient.java` | CdpClient — транспорт к запущенному Chrome (--remote-debugging-port=9222). Порт src/bridge/game_client.cjs: найти ЖИВУЮ вкладку игры, исполнять в ней  | 302 |
| `bridge/UpstreamBackend.java` | UpstreamBackend — Java-мост поверх уже работающего моста (Node). Нужен, чтобы переход на Java шёл постепенно: агент и внешние клиенты видят один и тот | 49 |
| `core/AgentCore.java` | AgentCore — главный цикл агента: OBSERVE → DECIDE → EXECUTE → VERIFY → LEARN. Раньше исполнитель навыков здесь был заглушкой (`return "SUCCESS"` без о | 154 |
| `core/SkillExecutor.java` | SkillExecutor — единственная точка исполнения навыков. Индексы берутся из SkillIndex (таблица моста), координаты — из снимка (quests[].turnInNpc) с за | 217 |
| `core/SkillIndex.java` | Единственный источник истины: индекс навыка для запроса {action:"step",idx:N}. Порядок обязан совпадать с python/hierarchical_env.py (SKILLS) и src/br | 48 |
| `core/SkillRegistry.java` | SkillRegistry — регистрирует навыки ИМЕННО теми именами, которые понимает мост. Прежний список содержал "turn_in" и "sell", тогда как мост ждёт "turn_ | 45 |
| `env/Entity.java` | Entity — any object in the game world (mob, NPC, resource node, item). Unified schema from game bridge. | 63 |
| `env/GameEnvironment.java` | GameEnvironment — связь с игрой через мост (:8791). Контракт моста (browser_bridge.cjs / src/bridge/actions.cjs): POST / {"action":"snapshot"}         | 163 |
| `env/ItemStack.java` | Inventory item stack | 12 |
| `env/Objective.java` | Quest objective | 12 |
| `env/PlayerState.java` | Player HP/level/position | 19 |
| `env/QuestEntry.java` | Quest entry from game | 23 |
| `env/QuestInfo.java` | Quest state container | 14 |
| `env/SnapshotMapper.java` | Разбор ответа моста ({ok, info}) в WorldState. Один маппинг на всех потребителей: мост отдаёт ПЛОСКИЙ снимок (browser_bridge.cjs: "info — это всегда п | 142 |
| `env/VendorItem.java` | Vendor item offer | 12 |
| `env/VendorState.java` | Vendor state | 13 |
| `env/WorldState.java` | WorldState — canonical source of truth for agent decisions. Single semantic source (no situation where game→bridge→info and game→observation differ). | 158 |
| `fsm/GoalFSM.java` | Quest FSM — состояния и переходы. Инвариант: qs == ACTIVE => accept_quest = INVALID Фаза ВЫВОДИТСЯ из наблюдения (syncFrom), а не переключается вручну | 74 |
| `mcp/WoofMcpServer.java` | WoOF MCP Server — HTTP JSON-RPC 2.0 Tools: status, start, stop, logs, config, build, test Run on port 8792 | 327 |
| `memory/Skill.java` | Skill — executable capability in Voyager architecture. Retrieved from SkillLibrary, composed into execution plans. | 28 |
| `memory/SkillLibrary.java` | SkillLibrary — registry of all available skills. Voyager pattern: retrieve → compose → execute → verify → save back. | 35 |
| `memory/WorldMemory.java` | WorldMemory — persistent memory of quest givers, locations, learned facts. | 39 |

## tests/ (3 проверок)

| Файл | Что проверяет | Строк |
|---|---|---|
| `tests/TestCdpClient.java` | Тест CDP-транспорта без браузера: поднимается tools/fake_cdp.cjs (две вкладки — мёртвая и живая) и проверяется ровно то, что ломалось в заглушке: выбо | 83 |
| `tests/TestJavaBridge.java` | Java-мост: контракт ответа и прозрачность к бэкенду. Верхний мост (8792) -> UpstreamBackend -> заглушка ниже (8793). | 103 |
| `tests/TestSkillIndex.java` | Таблица навыков обязана совпадать с src/bridge/actions.cjs (applyAction). | 26 |

## tools/ (6 файлов)

| Файл | Назначение | Строк |
|---|---|---|
| `tools/build.sh` | — | 10 |
| `tools/fake_bridge.cjs` | Контракт моста: step обязан нести idx, иначе это не шаг навыка | 281 |
| `tools/fake_cdp.cjs` | У вкладок должны быть РАЗНЫЕ url: иначе тест не может проверить, что клиент выбрал | 133 |
| `tools/fetch_libs.sh` | — | 16 |
| `tools/run_e2e.sh` | — | 70 |
| `tools/run_tests.sh` | — | 55 |
