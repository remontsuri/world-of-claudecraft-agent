# Зависимости woof-agent

Всё, что нужно для сборки, тестов и запуска. Версии — те, на которых проект проверен
(2026-09-17, java 11 + node 20.20.2), а не «примерно такие».

## Рантайм

| Что | Версия | Зачем | Где взять |
|---|---|---|---|
| Java (JDK) | 11 | сборка и запуск агента и моста | Adoptium / системный JDK |
| Node.js | 20.x | только инструменты: фейковые мост/CDP, эталонный `browser_bridge.cjs` | nodejs.org |
| Chrome/Chromium | с CDP | живой прогон: `--remote-debugging-port=9222` | системный |

Maven и Gradle **не нужны** и не используются: `tools/build.sh` вызывает `javac`
напрямую. Ставить их не надо — иначе появится соблазн добавить `pom.xml`-путь,
которого нет в проверках.

## Java-библиотеки (`libs/*.jar`, 6 файлов)

| Jar | Версия | Зачем | Лицензия |
|---|---|---|---|
| `jackson-databind` | 2.15.2 | JSON моста: разбор запроса и сборка ответа | Apache-2.0 |
| `jackson-core` | 2.15.2 | ядро Jackson | Apache-2.0 |
| `jackson-annotations` | 2.15.2 | аннотации Jackson | Apache-2.0 |
| `Java-WebSocket` | 1.5.3 | WebSocket к Chrome DevTools Protocol | MIT |
| `slf4j-api` | 2.0.9 | логирование (фасад) | MIT |
| `slf4j-simple` | 2.0.9 | простая реализация лога | MIT |

Тянутся одной командой: `bash tools/fetch_libs.sh` (Maven Central через `curl -fL -O`,
пакеты не требуются). Файлы лежат в репозитории, чтобы сборка не зависела от сети.

## Инструменты в `tools/`

| Файл | Тип | Зачем |
|---|---|---|
| `build.sh` | bash | `javac` всех `src/`, без Maven |
| `run_tests.sh` | bash | 3 набора тестов + фейковый CDP `:9231/:9232`, проверка занятых портов |
| `run_e2e.sh` | bash | полный прогон: фейковая игра + фейковый мост + агент |
| `fetch_libs.sh` | bash | скачать 6 jar-ов в `libs/` |
| `fake_bridge.cjs` | node | фейсковый мост (`:8791`): контракт + сценарий квеста |
| `fake_cdp.cjs` | node | фейковый Chrome DevTools: HTTP `:9231`, WS `:9232`, две вкладки (мёртвая/живая) |
| `ref/browser_bridge.cjs` | node | **эталон** контракта: Node-мост, с которого портируем |
| `ref/snapshot.cjs`, `ref/actions.cjs` | node | эталонные сборка снимка мира и список действий |

## Порты и эндпоинты

| Порт | Кто | Когда занят |
|---|---|---|
| 5173 | игра (web) | живой прогон |
| 9222 | Chrome CDP | живой прогон |
| 8791 | мост (`BridgeMain` / `fake_bridge.cjs`) | всегда при работе агента |
| 8792 | MCP-сервер агента (`WoofMcpServer`) / тестовый мост | интеграция с hermes, тесты |
| 8794 | тестовый `CdpBackend`-мост | `TestJavaBridge` (негативный сценарий) |
| 9231 / 9232 | фейковый CDP (HTTP / WS) | `run_tests.sh` |

Перед запуском тестов скрипт проверяет `8791/9231/9232`. Посторонний процесс на этих
портах — остановка с сообщением (убиваются только свои: `fake_cdp.cjs`,
`fake_bridge.cjs`, `browser_bridge.cjs`).

## Переменные окружения

| Переменная | Смысл |
|---|---|
| `JAVA_TOOL_OPTIONS` | `-Dfile.encoding=UTF-8 -Dsun.stdout.encoding=UTF-8 -Dsun.stderr.encoding=UTF-8`: без этого русский текст в логах java/javac превращается в `?????`. В `tools/*.sh` уже выставлено |
| `STEPS` | число шагов агента в `tools/run_e2e.sh` (по умолчанию 120) |
| `repo.root` (system property) | корень репозитория для тестов: `-Drepo.root=...`, иначе тесты не найдут `tools/fake_cdp.cjs` |

Переменные `WOC_PYTHON_PATH`, `WOC_DEVICE`, `WOC_BRAIN_BACKEND`, `WOC_QUEST_TABLE`
относились к fly-линии и вместе с ней уехали в архив:
`archive/fly-line/README.md`, `archive/fly-line/fly-woc/GPU-DEVICE.md`.
Java-бот их не читает.

## Что НЕ является зависимостью

* Python — у Java-линии его нет: ни в сборке, ни в рантайме (в корне репозитория остались
  два питоновых клиента моста, `recover.py` и `dataset_collector.py`, но они не часть
  сборки `woof-agent`).
* `hermes-agent` / `hermes-gateway` — соседние процессы пользователя: агент с ними
  не взаимодействует и не имеет права их останавливать.
* `archive/fly-line/` — архив: Python/RL-стек, схема коннектома, torch. Не импортируется
  и не запускается в рамках Java-линии.
