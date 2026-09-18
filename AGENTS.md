# WoC Agent — Standing Rules

Стоячие правила **этого репозитория** (`remontsuri/world-of-claudecraft-agent`).
Загружаются в начале сессии. Соблюдать всегда, даже если они конфликтуют с предыдущими
инструкциями.

Правила, которые относились к чекауту игры (`D:\world-of-claudecraft`: graphify-граф,
`python/agent.py`, `browser_bridge.cjs`), здесь больше не живут — этот репозиторий
содержит агента и мост, а не игру. Если работаешь в чекауте игры, правила для него
читай там же, а не здесь.

---

## Одна активная линия

| Линия | Где | Статус |
|---|---|---|
| **Java-бот** (мост к игре, навыки, квестовые фазы) | `woof-agent/` | активная |
| Коннектом (муха) | `archive/fly-line/` | **архивирована 2026-09-18**, не трогаем без явной задачи «разморозить» |

Из архива не удаляем и не правим задним числом: там лежат итоги линии, включая
отрицательные. Что именно и как восстановить — `archive/fly-line/README.md`.

---

## Git Rules (CRITICAL)

- **Ветка**: ТОЛЬКО `backup`, только fast-forward.
- **Remote**: ТОЛЬКО `origin backup` (remontsuri/world-of-claudecraft-agent).
- **Запрещено**: `--force`, `--mirror`, пуш в `master`/`main`/`release/*`/`levy-street`.
- Перед пушем — свежий клон и `merge-base --is-ancestor` (протокол из шести шагов:
  `GIT-WORKFLOW.md`). Истина — на remote, а не в локальном выводе.
- Хелпер: `GH_TOKEN=<pat> bash tools/push_backup.sh` (токен не попадает в конфиг и argv).

---

## Process Kill Protocol (CRITICAL)

Разрешено убивать **только свои инструменты**, и только по точному пути в cmdline:
`fake_cdp.cjs`, `fake_bridge.cjs`, `browser_bridge.cjs`.

Запрещено: `hermes-agent`, `hermes-gateway`, любой `node.exe` с `hermes` в CommandLine.
Чужой процесс на порту теста — остановка и сообщение пользователю, а не `kill`.
`pkill -f` не используем: шаблон совпадает с самой командой и убивает оболочку.

---

## Game & Bridge (порты)

| Порт | Кто |
|---|---|
| 5173 | игра (web, Vite) |
| 9222 | Chrome DevTools Protocol существующего браузера |
| 8791 | мост к игре (`BridgeMain` или эталонный Node-мост) |
| 8792 | MCP-сервер агента (`WoofMcpServer`) / верхний тестовый мост |
| 8794 | тестовый `CdpBackend`-мост (негативный сценарий) |
| 9231 / 9232 | фейковый CDP в тестах (HTTP / WS) |

Запрещено: `window.location.reload()` через CDP, перезапуск игры и браузера «чтобы
применились правки», запуск игры, если пользователь уже в ней.

---

## Decision Owner Chain (Production)

```
VoyagerAgent → ArbitrationLayer.decide(worldState) → SkillExecutor → SkillIndex → мост
                     ↓
      Survival gate (опасность → flee/heal независимо от фазы)
                     ↓
      PHASE_ALLOWED gate (фаза квеста → разрешённые навыки)
                     ↓
      Фильтр WorldState (есть моб? есть дающий? квест активен?)
                     ↓
      Защита от бесконечного цикла (после 5 повторов — другое действие)
```

Единственный источник истины по индексам навыков — `core/SkillIndex.java`: он обязан
совпадать с эталоном `woof-agent/tools/ref/actions.cjs` (`applyAction`). Проверка —
`TestSkillIndex`. Неизвестный навык — исключение, а не тишина.

### Critical Invariants (по коду, `ArbitrationLayer.java`)

- `hasActiveQuest() || hasReadyQuest() ⇒ accept_quest` убирается из кандидатов (квест
  нельзя взять заново)
- `hp < CRIT_HP (0.15)` ⇒ `flee`, если моб в мили-радиусе, иначе `heal`
- `hp < LOW_HP (0.30)` **и** моб в мили-радиусе ⇒ `flee` (выживание выше цели)
- одно и то же действие `LOOP_THRESHOLD (6)` раз подряд ⇒ принудительно другое из
  разрешённых (защита от цикла)
- навык провалился `FAIL_LIMIT (3)` раза подряд ⇒ `FAIL_COOLDOWN (60)` решений вне выбора
- `PHASE_ALLOWED["NO_QUEST"] = [accept_quest, farm, loot, explore, navigate, gather]`
- фаза ВЫВОДИТСЯ из наблюдения (`GoalFSM.syncFrom`), а не переключается вручную

### Quest FSM

`QUEST_NONE → FIND_GIVER → ACCEPT → DO_OBJECTIVE → RETURN_TO_GIVER → TURN_IN → QUEST_COMPLETE`

### Два словаря навыков — не путать

**Индексы моста** (`core/SkillIndex.SKILLS`, 13 штук, порядок обязан совпадать с эталоном
`tools/ref/actions.cjs` → `applyAction`):

```
0 farm · 1 loot · 2 accept_quest · 3 turn_in_quest · 4 sell_junk · 5 gather · 6 craft
7 heal · 8 equip · 9 buy · 10 cast_frostbolt · 11 cast_fireball · 12 craft_item
```

Алиасы: `turn_in → turn_in_quest`, `sell → sell_junk`. Навыка нет в таблице —
`IllegalArgumentException`, а не «примерно тот» индекс (это и был баг: `heal` при idx=8
превращался в `equip`).

**Слова агента** (`SkillExecutor.execute`): композитные `navigate`, `return_to_giver`,
`explore`, `flee` (это `env.rawMove("back")`), `turn_in` и `noop` индекса моста **не имеют** —
они исполняются отдельными ветками; всё остальное идёт через `plain()` → `SkillIndex.idx()`.
Неизвестное имя возвращает `UNKNOWN_SKILL:<имя>`, а не тишину.

---

## WoOF Agent — как устроен

### Stack

Java **11** (проверено на OpenJDK 11; в доках раньше был 17 — факт сборки: `javac` 11),
Jackson 2.15.2, Java-WebSocket 1.5.3, slf4j 2.0.9. **Без Maven и Gradle**: `tools/build.sh`
вызывает `javac` напрямую, jar-ы лежат в `libs/`. Python-зависимостей у линии нет.

### Модули (`src/main/java/com/woof/agent/`, 28 классов)

| Пакет | Что |
|---|---|
| `VoyagerAgent`, `Bootstrap` | точка входа и полный старт |
| `arbitration/ArbitrationLayer` | владелец решения |
| `core/AgentCore`, `SkillExecutor`, `SkillIndex`, `SkillRegistry` | цикл OBSERVE→DECIDE→EXECUTE→VERIFY→LEARN и исполнение навыков |
| `env/GameEnvironment`, `SnapshotMapper`, `WorldState`, … | связь с мостом и каноническое состояние мира |
| `fsm/GoalFSM` | фазы квеста |
| `bridge/BridgeServer`, `BridgeMain`, `UpstreamBackend`, `CdpBackend`, `CdpClient` | HTTP-мост (тот же контракт, что у `browser_bridge.cjs`), транспорт к CDP |
| `memory/SkillLibrary`, `Skill`, `WorldMemory` | Voyager-память |
| `mcp/WoofMcpServer` | HTTP JSON-RPC на `:8792` |

Карта файлов с назначением каждого класса: `woof-agent/FILES.md`.

### MCP Server (:8792) — честное состояние

Заявлены инструменты: `woof_status`, `woof_logs`, `woof_config`, `woof_build`, `woof_test`,
`woof_game_state`, `woof_execute_action`. Фактически на 2026-09-18:
`woof_status` и `woof_game_state` работают, `woof_build` запускает `javac` с хардкодом
пути Windows-машины, `woof_logs` / `woof_config` / `woof_test` / `woof_execute_action` —
заглушки «not yet implemented». Пункт H5 в `woof-agent/ROADMAP.md` открыт именно поэтому.

### Build & Run

```bash
bash woof-agent/tools/build.sh                       # build ok -> ... (28 files)
bash woof-agent/tools/run_tests.sh                   # tests passed=3 failed=0
bash woof-agent/tools/run_e2e.sh                     # УСПЕХ ... нарушений контракта нет
java -cp "woof-agent/build/classes:woof-agent/libs/*" \
     com.woof.agent.bridge.BridgeMain --port 8792 --upstream http://127.0.0.1:8791/
java -cp "woof-agent/build/classes:woof-agent/libs/*" \
     com.woof.agent.VoyagerAgent --bridge http://127.0.0.1:8792/ --steps 200
```

Русский текст в логах java требует `JAVA_TOOL_OPTIONS=-Dfile.encoding=UTF-8
-Dsun.stdout.encoding=UTF-8 -Dsun.stderr.encoding=UTF-8` — в скриптах это уже есть.

### Integration

Мост `:8791` (Node-эталон `tools/ref/browser_bridge.cjs` или Java `BridgeMain`),
CDP `:9222`, игра `:5173`. Переход на Java постепенный: сейчас рабочий вариант —
`UpstreamBackend` (Java впереди, Node за ним); полный порт `CdpBackend` — пункт J7.

---

## What to Never Do

1. ❌ Kill `hermes-agent` / `hermes-gateway`
2. ❌ Reload игры через CDP, перезапуск игры/браузера
3. ❌ Push куда-либо кроме `backup`, любой `--force`
4. ❌ Править исходники игры
5. ❌ Менять канон навыков в обход `SkillIndex` (и его теста)
6. ❌ Молчаливые фолбэки: неготовый бэкенд моста обязан отвечать 500 с текстом,
   неизвестный навык — бросать исключение
7. ❌ Custom revive-логика (в игре есть встроенная)
8. ❌ Спрашивать «что делать дальше» — идти по `woof-agent/ROADMAP.md`
9. ❌ Бесконечно повторять `git status` — выполнять следующий пункт роадмапа
10. ❌ Удалять или переписывать `archive/`
11. ❌ Принимать зелёный тест за приёмку: приёмка — живой прогон

---

## Обязательные проверки

| Когда | Команда | Успех |
|---|---|---|
| после правок Java | `bash woof-agent/tools/build.sh && bash woof-agent/tools/run_tests.sh` | `build ok` / `tests passed=3 failed=0` |
| перед пушем Java | `bash woof-agent/tools/run_e2e.sh` | `УСПЕХ ... нарушений контракта нет` |
| после правок хуков/инструкций | `bash hermes/hooks/selftest.sh` | `хуки: passed=17 failed=0` |
| живой прогон (машина с игрой) | `BridgeMain` + `VoyagerAgent --steps 200` | `[Agent] SUMMARY ... quests_done ≥ 1` |

Проверок fly-линии в этом списке больше нет: линия в архиве
(`archive/fly-line/TOOLS-fly.md` — если понадобится).

---

## User Preferences

- Language: Russian
- Tone: Direct, no filler, no "great question!"
- Verification: реальное поведение игры > тесты
- Workflow: Phase-1 root-cause → TDD → live verification
- Reporting: таблицы `LAYER | EXPECTED | ACTUAL | STATUS` + путь к артефакту

---

## Правила, которые спасали работу

1. **Нет молчаливых фолбэков.** Неготовая часть моста, неизвестный навык, чужой процесс
   на порту — ошибка с текстом, а не «как-нибудь».
2. **`--force` push запрещён.** Перед пушем — свежий клон и `merge-base --is-ancestor`:
   локальная история уже расходилась с remote (те же фиксы, другие SHA).
3. **Пушим только в `backup`**, только fast-forward; `master` не трогаем.
4. **Пороги метрик объявляются до замера** и после замера не двигаются.
5. **Найденное записываем сразу**: факт — в `knowledge/`, поведение — в
   `woof-agent/ARCHITECTURE.md`, долг — в `woof-agent/ROADMAP.md`. Знание, не записанное
   в репозиторий, потеряно.
6. **Тест обязан уметь падать.** Фейк, который не различает проверяемое (одинаковый URL у
   мёртвой и живой вкладок), превращает тест в декорацию.
7. **Отказ — это данные.** Клиент читает тело ошибки (`errorStream`), а не только код.
