# Исследование: хуки против «тупления» hermes + AST-слой impact-анализа

Дата: 2026-09-20. Автор: агент Arena (по директиве владельца).
Статус: **исследование завершено, решения приняты, код не написан** (ждёт команды).

Задача владельца: сделать так, чтобы hermes «не тупил и не делал одно и то же»,
не изобретая существующее. Ориентир архитектуры, названный владельцем — его
собственный инструмент **PyScanPyAST** (astroid + networkx, двусторонний BFS,
цепочки импортов, CLI `scanner.py <проект> [--init <модуль>]`).

---

## 0. Главный вывод

**Писать свой AST-сканер не нужно.** Каждый модуль PyScanPyAST уже существует
в виде поддерживаемого инструмента, и почти весь нужный функционал доступен
hermes **декларацией в `~/.hermes/config.yaml`**, а не кодом:

| Модуль PyScanPyAST | Готовый аналог | Как подключается к hermes |
|---|---|---|
| `ast_parser` (astroid) + `graph_builder` (networkx) | **Serena** (LSP: pyright/jedi) · **pyan3 2.6** (ast+symtable) · **tree-sitter-analyzer (TSA)** · **Codebase-Memory** | MCP-сервер → `mcp_servers:` |
| `association_engine` (BFS upstream/downstream) | Serena `find_referencing_symbols` · TSA `nav action=callers/callees` · pyan3 `direction=up/down` | MCP-инструмент |
| `chain_report` (цепочки импортов) | pyan3 `--paths-from A --paths-to B` (DFS, shortest-first) · TSA `action=call_path` · Codebase-Memory call-path tracing | MCP/CLI |
| `targeted_deps` (кто импортирует цель) | Serena `find_referencing_symbols` · TSA `--affected FILE` · **pytest-impacted** (тесты) | MCP/CLI |
| `reporter` (топ in-degree/out-degree, мёртвый код) | TSA `health action=dead/matrix/heatmap` · pyan3 depth/direction · Codebase-Memory hub detection | MCP |
| `ini_reader`/`file_scanner` (scope, исключения) | grimp/import-linter контракты · `fullSuiteTriggers` у vitest-affected | конфиг |
| C-слой (владелец: «для C — Clang») | **Serena через clangd** (практично) · **cppgraph** (compiler-exact SCIP, тяжело) · clang-query/clang-tidy (матчеры «все вызывающие f») | MCP / CLI |

Единственное, что **действительно** нужно написать самим — repeat-guard и
склейку «состояние репо → контекст в модель». И то не с нуля: алгоритм берётся
из prior art (см. §4), а в hermes уже есть половина (см. §3).

---

## 1. Ключевой факт: hermes — MCP-клиент

Раньше мы исходили из того, что расширять hermes можно только shell-хуками.
Это не так. `~/.hermes/config.yaml` поддерживает `mcp_servers:` — hermes
подключается к MCP-серверу, автоматически обнаруживает его инструменты и
регистрирует их рядом со встроенными (префикс `mcp__`, toolset `mcp-<name>`).

```yaml
mcp_servers:
  serena:
    command: "uvx"
    args: ["--from", "git+https://github.com/oraios/serena",
           "serena", "start-mcp-server",
           "--context", "ide-assistant", "--project", "D:/repo"]
    tools:
      include: [find_symbol, find_referencing_symbols, symbol_overview,
                get_diagnostics_for_file, activate_project]
      prompts: false
      resources: false
    timeout: 120
    idle_timeout_seconds: 600     # пересоздавать stdio-процесс после простоя
    trust: untrusted              # fail-closed: write-инструменты требуют подтверждения
```

Поля, которые важны для нас:

- `tools.include/exclude` — точные имена **или glob** (`get_zones_*`). Без них
  в контекст вывалится 20+ инструментов.
- `lazy: true` — зарегистрировать инструменты из кэша схем, а процесс поднять
  только при первом вызове (нужен один «живой» коннект для заполнения кэша).
- `idle_timeout_seconds` / `max_lifetime_seconds` — ресайкл stdio-сервера.
- `trust: untrusted` — любой write-инструмент (без `readOnlyHint: true`)
  требует подтверждения; нераспознанное значение трактуется как untrusted
  (fail-closed). Serena умеет `replace_symbol_body`/`insert_after_symbol` —
  то есть **может писать**, поэтому `trust: untrusted` обязателен.
- `enabled: false` — сервер пропускается полностью, конфиг остаётся.
- Интерполяция `${ENV_VAR}` из `~/.hermes/.env` — секреты только там
  (соответствует нашему правилу «секреты только из env»).
- Плагины могут сами звать MCP: `ctx.call_mcp(server, tool, arguments, timeout=30)`.

Проверка: `hermes tools` показывает встроенные toolset'ы и `N/M tools from <server>`.

---

## 2. Точные имена инструментов hermes (для `matcher` в хуках)

Это то, чего у нас не было: наш старый `hooks.json` использовал выдуманные
имена. Реальные (toolsets reference):

| Toolset | Инструменты |
|---|---|
| `terminal` | `terminal`, `process` |
| `file` | `read_file`, `write_file`, `patch`, `search_files` |
| `web` | `web_search`, `web_extract` |
| `browser` | `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_press`, `browser_scroll`, `browser_back`, `browser_console`, `browser_get_images`, `browser_vision`, `browser_cdp`, `browser_dialog`, `web_search` |
| `code_execution` | `execute_code` |
| `delegation` | `delegate_task` |
| `skills` | `skills_list`, `skill_view`, `skill_manage` |
| `todo` / `memory` / `clarify` / `session_search` / `cronjob` | `todo`, `memory`, `clarify`, `session_search`, `cronjob` |
| MCP | `mcp__<server>__<tool>` |

Практические следствия:

1. **`edit` не существует** — редактирование это `patch` (fuzzy, 9 стратегий,
   возвращает unified diff, сам гоняет синтаксические проверки) и `write_file`
   (полная перезапись; **отказывается** писать, если файл не был прочитан в
   этой задаче или изменился на диске). Наш matcher `terminal|write_file|patch|edit`
   надо заменить на `^(terminal|process|write_file|patch|execute_code|delegate_task)$`.
2. `browser_cdp` и `browser_dialog` **регистрируются только если CDP-эндпоинт
   доступен на старте сессии** (`/browser connect`, `browser.cdp_url`,
   Browserbase, Camofox).
3. `write_file` уже имеет встроенный anti-blind-write guard — это надо не
   дублировать, а дополнять (он не ловит повторы `patch` с тем же diff).

---

## 3. Встроенная защита от повторов в hermes (сначала включить её)

`agent/tool_guardrails.py`, конфиг в `~/.hermes/config.yaml`:

```yaml
tool_loop_guardrails:
  warnings_enabled: true
  hard_stop_enabled: true          # ПО УМОЛЧАНИЮ FALSE — это главная причина «тупит»
  non_interactive_hard_stop_enabled: true
  warn_after:
    exact_failure: 2
    same_tool_failure: 3
    idempotent_no_progress: 2
  hard_stop_after:
    exact_failure: 3
    same_tool_failure: 5
    idempotent_no_progress: 3
  loop_caps:
    max_web_searches: 20
    max_subagents: 10
agent:
  max_turns: 40                    # по умолчанию none
  budget_warning_ratio: 0.75
```

Что известно из трекера hermes (проверить на версии владельца!):

- **issue #112535** (16.09.2026): `hard_stop_enabled: false` по умолчанию →
  зафиксировано ~500 байт-идентичных вызовов подряд. Критерий приёмки там —
  блок (не предупреждение) после 5 повторов по умолчанию.
- **PR #101833**: `reset_for_turn()` обнулял `_identical_streak_*`/`_no_progress`
  → повторы через ходы не накапливались. Фикс — персистить в `__init__`.
- **issue #34610** и **#46804**: «успешные» мутирующие вызовы без прогресса
  (например `browser_navigate` на 404) не считаются вообще. Предложен ключ
  `tool_repetition` (`warn_after.tool_repetition: 5`,
  `hard_stop_after.tool_repetition: 8`) — в #46804 прямо сказано, что
  **конфиг эти ключи уже принимает, но они no-op**. То есть на части версий
  можно просто объявить `tool_repetition` и он заработает после мержа патча.
- **PR #85352** (мерж-кандидат): считать по **сигнатуре вызова**, а не по хешу
  результата, потому что компрессия контекста подменяет тело повтора заглушкой
  `[Duplicate tool output — same content as a more recent call]`, а некоторые
  инструменты сами возвращают `{"status":"unchanged","content_returned":false}`.
  При этом в ревью найдены ложные срабатывания: (а) легитимный поллинг
  (чтение файла, который меняет внешний процесс) начал считаться no-progress;
  (б) `_no_progress` переживает `reset_for_turn()` → новый ход пользователя,
  который легитимно перечитывает тот же файл, упирается в блок.
  Итоговое правило дизайна: **сбрасывать счётчик, когда результат реально новый**,
  и **сбрасывать окно на новом пользовательском ходе**.
- **PR #106428** (мержнут): stall guard ловит **повторяющиеся мульти-вызовные
  циклы**, а не только соседние повторы (порт oh-my-pi#10521). Значит на свежей
  версии цикл A,B,A,B уже детектируется ядром.
- **PR #67538**: assistant-turn repetition guard — «подтолкнуть» идентичные
  ходы без прогресса, опциональный чистый abort.

**Вывод:** прежде чем писать свой guard, надо (1) включить `hard_stop_enabled`,
(2) узнать версию hermes, (3) проверить, есть ли `tool_repetition` и
мульти-цикловой stall guard. Наш собственный хук оправдан только как
**дополнение**: он видит состояние репо (чего ядро не видит) и работает
одинаково на любой версии.

---

## 4. Prior art по repeat-guard: алгоритм берём, не изобретаем

| Источник | Что берём |
|---|---|
| **openfang** `loop_guard.rs` (через hermes issue #481) | `SHA256(tool_name + serialized_args)`; скользящее окно последних N (default 10); exact repetition ≥3 подряд → warn; эскалация **warn → backoff suggestion → block**; `exempt_tools` (поллинг); phase 2 — **ping-pong (A-B-A-B)** и **cycle (A-B-C-A-B-C)** детекция |
| **`tool-loop-guard`** (PyPI, `pip install tool-loop-guard`, 0 зависимостей, Py3.9+, 23 теста) | Готовая реализация скользящего окна: `LoopGuard(window=10, threshold=3)`, `guard.record(name, args)` → `LoopDetected`. Покрывает single-tool loops, multi-tool interleaving, границы окна, пороги, reset. **Можно использовать как библиотеку внутри нашего хука вместо своего кода** |
| **`pi-loop-police`** (расширение Pi, TS) | Самая проработанная схема: каждый вызов хешируется (name+args) в историю; проверяется, **повторяют ли последние W вызовов в точности предыдущие W** → цикл **любой** длины, не только одиночные. Совпало → вызов **блокируется на месте** (не исполняется), а recovery-сообщение возвращается как единственный результат этого инструмента. Плюс: `FILE_SCAN_LIMIT=20` реальных чтений одного пути до блока; `REREAD_WINDOW=10` + `REREAD_RATIO=0.4` — доля перечитываний **неизменённых** файлов в окне до блока; `SEARCH_EXPAND_LIMIT=3` разных путей для одного паттерна поиска; `TOOL_LOOP_EXEMPT`; `TOOL_LOOP_BAN` 0=выкл/1=блок пока повторяется/2=бан на сессию; `HOOK_CMD` + `HOOK_LOG` (**JSONL на каждое срабатывание** — это ровно наш `.hermes/journal.jsonl`); `CONSECUTIVE_LOOP_LIMIT=2` — эскалация сообщения |
| **data-fair/agents PR #56** | Один плоский step-backstop (100) как у OpenHands/browser-use — тратить бюджет не его задача; repeated-call guard сравнивает **вызовы И их результаты**, чтобы одинаковый вызов с другим выводом (поллинг, перечитывание после изменения) считался прогрессом; параллельные вызовы сравниваются **как множество**; напоминание инжектируется в следующий запрос модели на 3-м идентичном шаге, стоп на 5-м (лестница OpenHands SDK); напоминание **не попадает в сохраняемый транскрипт** |
| **particula.tech** (no-progress guard) | Лимиты шагов повтор не ловят: LangGraph `recursion_limit=25` и LangChain `max_iterations=15` — это backstop'ы, которые срабатывают **после** того, как бюджет потрачен. Нужен guard по `(tool, args, result)`, стоп на 2–3 повторе. Нативного решения в LangChain/LangGraph **нет** (issue #36139 закрыт как external feature request) — ставится через middleware. Готовый ~20-строчный `NoProgressGuard(max_repeats=3, window=6)` с `deque(maxlen=window)` |
| **evener #94** | Из всех харнессов только **gemini-cli `LoopDetectionService`** ловит циклы A,B,C в потоке; Cline, Roo, Goose, crewAI — только соседние вызовы. Рекомендации оттуда: ослаблять правила для read-only, сбрасывать окно на мутирующем вызове (hermes-agent #35573) |
| **agent-zero #1690** | `temperature 0` → идентичные выводы модели. **Текстовое «предупреждение» игнорируется** — нужен блок на уровне действия (`force_response`/`blocked_tools`). Корневые причины: у описаний инструментов нет стоп-условий; факт вызова «теряется» при суммаризации скретчпада |
| **openclaw #120415** | Без guard'а повтор останавливается только посторонним wall-clock таймаутом. Локальный stopgap — N=3 последовательных идентичных сигнатуры |

### Сведенный алгоритм (то, что мы реализуем)

```
сигнатура = sha256(tool_name + canonical_json(args) + repo_state_hash)
  canonical_json: sort_keys, без пробелов, нормализованные пути (слэши, lower для Windows-диска)
  repo_state_hash: sha256(git status --porcelain + git diff --stat) — «изменилось ли состояние репо»

журнал: .hermes/journal.jsonl, последняя запись + скользящее окно W=20 в памяти

правила (по возрастанию жёсткости):
 1. exempt_tools = {process, todo, memory, clarify, session_search, browser_snapshot}
    → только лог, без счёта (легитимный поллинг/статус)
 2. read-only (read_file, search_files, web_search, web_extract)
    → пороги мягче (window 20, warn 4, block 8), и блок только если
       REREAD_RATIO ≥ 0.4 (доля перечитываний неизменённых файлов) — по pi-loop-police
 3. mutating (terminal, write_file, patch, execute_code, delegate_task, browser_*)
    → warn на 2-м идентичном, block на 3-м (порог объявлен ДО внедрения)
 4. цикл любой длины: последние W вызовов == предыдущие W (W=1..5) → block   [pi-loop-police]
 5. ping-pong A,B,A,B и цикл A,B,C в окне 20 → warn                          [openfang phase 2]
 6. сброс счётчика сигнатуры, если результат реально новый (хеш результата
    отличается И это не заглушка дедупликации/компрессии)                    [PR #85352 review]
 7. сброс окна при смене пользовательского хода                              [PR #85352 review]
 8. при блоке: вызов НЕ исполняется; в модель возвращается сообщение с
    (a) фактом повтора и счётчиком, (b) последним результатом,
    (c) конкретным требованием сменить стратегию                             [agent-zero: текст игнорируется → блокировать действие]
 9. каждое срабатывание → строка JSONL в журнал (время, tool, сигнатура,
    решение, счётчик) — наблюдаемость без чтения транскрипта                 [pi-loop-police HOOK_LOG]
```

Почему всё-таки пишем свой, а не `pip install tool-loop-guard`:
библиотека не знает ни состояния репо (п. 6/сигнатура), ни политики нашего
репозитория (запрет правок игры, force-push, убийства hermes-*), ни нашего
журнала. Но **её алгоритм скользящего окна можно взять как зависимость**
(`python_dependencies: ["tool-loop-guard>=…"]` в `plugin.yaml`), если владелец
согласен на внешнюю зависимость; иначе ~40 строк своих с тестами.
Решение за владельцем — см. §8, вопрос Q2.

---

## 5. Контракт хуков hermes (исправленная версия)

Четыре системы. Наш старый `hermes/hooks/hooks.json` несовместим **ни с одной**.

| Система | Регистрация | Где живёт | Где работает | Может блокировать вызов | Может инжектировать контекст |
|---|---|---|---|---|---|
| Gateway hooks | `HOOK.yaml` + `handler.py` | `~/.hermes/hooks/<name>/` | только gateway | нет | нет |
| **Plugin hooks** | `ctx.register_hook()` в плагине | `~/.hermes/plugins/<name>/` **или `./.hermes/plugins/<name>/`** | CLI + Gateway | **да** (`pre_tool_call`) | **да** (`pre_llm_call`) |
| Shell hooks | блок `hooks:` в profile `config.yaml` | по соглашению `~/.hermes/agent-hooks/` | CLI + Gateway + Desktop/TUI/dashboard | да | да |
| Outbound webhooks | `hooks.outbound:` в `config.yaml` | — | CLI + Gateway | нет | нет |

### 5.1 Плагины (то, что нам нужно)

```
.hermes/plugins/woof-guard/
├── plugin.yaml      # манифест
└── __init__.py      # register(ctx)
```

**Два обязательных условия, без которых плагин молчит** (это вторая причина
«тупления», после несовместимого `hooks.json`):

1. Project-local плагины в `./.hermes/plugins/` **отключены по умолчанию** —
   нужен `HERMES_ENABLE_PROJECT_PLUGINS=true` (или `=1`) до запуска hermes.
2. **Все** плагины opt-in: discovery их находит (видно в `hermes plugins`),
   но ничего не грузится, пока имя не добавлено в `plugins.enabled` в
   `~/.hermes/config.yaml` (или `hermes plugins enable <name>`).

Манифест v1 + опциональные поля v2:

```yaml
name: woof-guard
version: 1.0.0
description: Anti-repeat guard, repo-state context, impact-set verification for woof-ts
author: MaleCNS (CC BY 4.0)
manifest_version: 2          # опционально; максимум 2
api_version: 1               # отдельная ось от manifest_version
python_dependencies:         # декларация; hermes НЕ ставит сам, только подсказывает
  - "pyyaml>=6,<7"
config_schema:               # ключи в plugins.entries.woof-guard.settings
  journal_path: {type: str, default: ".hermes/journal.jsonl", description: "JSONL journal"}
  window:       {type: int, default: 20, description: "sliding window size"}
  block_after:  {type: int, default: 3,  description: "identical mutating calls before block"}
license: CC-BY-4.0
tags: [guardrails, woof]
```

Возможности `ctx` (полный список из docs):
`register_tool(name=, toolset=, schema=, handler=)`, `register_hook(event, cb)`,
`register_command(name, handler, description)` (slash), `dispatch_tool(name, args)`,
`register_cli_command(name, help, setup_fn, handler_fn)`,
`inject_message(content, role="user", session_key=...)`,
`register_skill(name, path)` (namespace `plugin:skill`),
`register_system_prompt_section(id, str|callable, position="after_memory", max_chars=4000)`,
`ctx.llm.complete(...)` / `complete_structured(...)`,
`ctx.call_mcp(server, tool, arguments, timeout=30)`,
`ctx.has_plugin("other-plugin")`.

Сигнатуры коллбэков (важно — kwargs, а не позиционные):

```python
def register(ctx):
    ctx.register_hook("pre_tool_call", on_pre_tool)    # (tool_name, args, task_id, **kw)
    ctx.register_hook("post_tool_call", on_post_tool)  # (tool_name, params, result)
    ctx.register_hook("pre_llm_call", on_pre_llm)      # (session_id, user_message, is_first_turn, **kw) -> {"context": str}
    ctx.register_hook("post_llm_call", on_post_llm)    # (session_id, assistant_response, model, **kw)
    ctx.register_hook("on_session_start", on_start)    # (session_id, **kw)
    ctx.register_hook("on_session_end", on_end)        # (session_id, completed, interrupted, **kw)
    ctx.register_system_prompt_section(
        "woof.rules", RULES_TEXT,            # str ИЛИ callable(session_info)->str
        position="after_memory", max_chars=4000,
    )
```

Порядок и приоритет: plugin-хуки регистрируются раньше shell-хуков
(`discover_and_load()` → `register_from_config()`), поэтому при ничьей
**Python `pre_tool_call` block побеждает**. Первый валидный block выигрывает —
агрегатор возвращает результат, как только любой коллбэк дал
`{"action": "block", "message": <непустое>}`.

Ограничения системного промпта: ≤4000 знаков на секцию, суммарно 8000 знаков /
32 секции, ставится один раз на сессию, **замораживается при компрессии
контекста**. Поэтому статические правила — туда, а всё динамическое —
в `pre_llm_call`.

`pre_llm_call` вводит `context` в **USER** message, а не в системный — это
сделано намеренно, чтобы не ломать KV-кэш.

### 5.2 Shell-хуки (для Windows-обёрток и быстрого старта)

```yaml
hooks:
  pre_tool_call:
    - matcher: "^(terminal|process|write_file|patch|execute_code|delegate_task)$"
      command: "D:/repo/hermes/hooks/win/guard.cmd"
      timeout: 10
      fail_closed: true          # только для pre_tool_call; алиас failClosed
  pre_llm_call:
    - command: "D:/repo/hermes/hooks/win/context.cmd"
      timeout: 15
  pre_verify:
    - command: "D:/repo/hermes/hooks/win/impact.cmd"
      timeout: 60
hooks_auto_accept: false         # согласие при первом использовании на пару (событие, команда)
```

`matcher` — регулярка, **только для `pre_tool_call`/`post_tool_call`**.
`command` разбирается через `shlex.split`, запускается с `shell=False`.
`timeout` по умолчанию 60, максимум 300. Пустой вывод = no-op.

stdin (JSON): `{"hook_event_name", "tool_name", "tool_input", "session_id",
"cwd", "extra": {"task_id", "tool_call_id"}}` — **не** наша старая форма
`{"event","cwd","tool","command","paths","task"}`.

stdout (JSON), оба варианта валидны:
- `{"action": "block", "message": "…"}` или compat `{"decision": "block", "reason": "…"}`
- `{"action": "modify", "args": {…}}` — подменить аргументы
- `pre_llm_call` → `{"context": "…"}`
- `pre_verify` → `{"action": "continue", "message": "…"}`

События (`VALID_HOOKS` из `hermes_cli.plugins`): `pre_tool_call`,
`post_tool_call`, `pre_llm_call`, `post_llm_call`, `pre_verify`,
`on_session_start`, `on_session_end`, `on_session_finalize`, `on_session_reset`,
`subagent_start`, `subagent_stop`, `pre_api_request`, `transform_*`,
`pre_transcription`, `kanban_task_claimed|completed|blocked`.

`pre_verify` получает в payload `changed_paths` — это готовый вход для
impact-анализа, свой `git diff` дёргать не обязательно.

Таймауты: `pre_tool_call` при таймауте plugin-хука **fail closed**
(`plugins.hook_callback_timeout`, по умолчанию 30 с).

Отладка: `hermes hooks list`, `hermes hooks test <event> --for-tool <tool>`.
**Баг #115968** (0.21.3, 19.09.2026): `hooks test` не показывает решение при
ошибке/таймауте хука → проверять через `sh.run_once(...)` напрямую.

Отладка discovery плагина: (а) не в `plugins.enabled`; (б) неправильная
раскладка — нужен `plugin.yaml` плоско или **максимум один** уровень категории;
(в) нет `__init__.py` с `register(ctx)`; (г) не тот `kind`.

Прочее: `hermes plugins install owner/repo --ref <40-символьный SHA>` (теги и
ветки отвергаются), `hermes plugins pack export|install`, install-time
сканирование безопасности (паттерны эксфильтрации, reverse shell, обфускация,
prompt injection в доках) — наш код должен его проходить чисто.

---

## 6. AST/impact-слой по языкам: что ставить

### 6.1 TypeScript/JavaScript (наша активная линия `woof-ts/`)

**`vitest-affected`** — `npm install -D vitest-affected`. Плагин Vitest,
сделанный **именно для AI-агентов** («each agent runs ~20 tests in seconds
instead of 2,771 in minutes»).

```ts
// vitest.config.ts
import { defineConfig } from 'vitest/config';
import { vitestAffected } from 'vitest-affected';

export default defineConfig({
  plugins: [vitestAffected({
    ref: 'backup',
    verbose: true,
    statsFile: '.vitest-affected/stats.jsonl',
    // всё, что граф импортов не видит, но что ломает прогон:
    fullSuiteTriggers: ['evidence/', /^package\.json$/, /^vite\.config\./,
                        /^tsconfig.*\.json$/, /\.env/, 'tools/setup_game.sh'],
    staleCacheDays: 14,
    maxSelectiveRuns: 50,
  })],
  test: { include: ['tests/**/*.test.ts'] },
});
```

Как работает: первый прогон полный → runtime-reporter снимает
`importDurations` каждого теста → reverse dependency map в
`.vitest-affected/graph.json`; дальше `git diff` → delta-parse изменённых
файлов (oxc) → BFS по обратной карте → мутация `config.include`.
Заявленное: ~5 мс на выбор, 2771 тест/152 с → 22 теста/3.1 с.

Свойства, которые совпадают с нашими правилами:
- **никогда не пропускает тесты молча**: ошибка git / битый кэш / неполный граф
  → полный прогон с предупреждением (соответствует «no silent fallbacks»);
- `VITEST_AFFECTED_SHADOW=1` — теневой режим: прогоняет всё и логирует, что
  **выбрало бы**. Это наш способ проверить селекцию до того, как доверять ей;
- `VITEST_AFFECTED_DISABLED=1` — kill switch, побеждает всё;
- `threshold: 0.8` — если затронуто больше доли, уйти в полный прогон;
- config-файлы (`package.json`, `tsconfig.json`, `vitest.config.*`, lockfiles)
  и `setupFiles`/`globalSetup` **всегда** форсят полный прогон;
- предупреждает о протухшем кэше (14 дней / 50 селективных прогонов), но
  **никогда не форсит** полный прогон сам.

Требование: хук `configureVitest` появился в **Vitest 3.1.0** — проверить нашу
версию. Известные грабли из их skill-дока: re-экспорты лежат в `staticExports`,
не в `staticImports`; у dynamic import `.moduleRequest` не имеет `.value`;
oxc-parser pre-1.0 (пинить версию); не вызывать `project.globTestFiles()`.

Сравнение (их таблица): `vitest --changed` — мелкие зависимости, без
персистенции, пропускает транзитивные (#4933); `jest --onlyChanged` — только
прямо изменённые файлы; Nx affected — гранулярность проекта, не файла.

Дополнительно: **`testpick`** — coverage-based выбор; выигрывает на
runtime-вычисляемых связях (реестр/DI), когда статического края импорта нет
(`vitest related src/features/feat.ts` → «No test files found»). Их честное
замечание: покрытие выигрывает на runtime-связях, статический граф — когда
правка задевает ветку, которую записанный прогон не исполнял. Поэтому
**fallback на полный прогон обязателен**. У нас в `woof-ts/` как раз есть
runtime-связь: `WOOF_PARAMS=<file.json>` и `game` симлинк — их граф не увидит,
значит они обязаны быть в `fullSuiteTriggers`.

Статический контроль границ: **`tsc --noEmit`** остаётся обязательным шагом
гейта (vitest-affected его не заменяет).

### 6.2 Python (`woc-game/python/`, тулзы)

- **`pytest-impacted`** — `impacted-tests --module=pkg --git-mode=branch --base-branch=backup`.
  git diff → модули без импорта → astroid/парсер ruff → networkx → затронутые
  тесты. Стратегии: транзитивные импорты; conftest → все тесты каталога;
  изменение `uv.lock`/`requirements.txt`/`pyproject.toml` → все;
  `--impacted-invalidate-all`. **Это прямой аналог `targeted_deps`.**
- **`grimp` + `import-linter`** — контракты `layers` / `forbidden` /
  `independence` / `protected` / `acyclic_siblings`; вывод нарушенными
  **цепочками** (аналог `chain_report`); `lint-imports --contract --no-cache
  --show-timings`; конфиг `[tool.importlinter]`; годится в pre-commit.
- **`tach`** (Rust, `tach check`) — быстрее, import-linter как фолбэк.
- **`pyan3` ≥2.6** — уже умеет то, что делает `association_engine`:
  `direction="up"|"down"|"both"` (только вызывающие / только вызываемые),
  `depth=0|1|2|None` (модули / +классы / +методы), `exclude=["test_*.py"]`,
  `pyan3 src/ --paths-from pkg.mod.caller --paths-to pkg.mod.target`
  (DFS, shortest-first, `--max-paths` default 100), Python API
  `pyan.create_callgraph(...)`, `CallGraphVisitor.find_paths(src, tgt)`.
  GPL v2 — учитывать при распространении.
- `pytest-testmon` (по покрытию: точнее, тяжелее, конфликтует с другими),
  `pytest-picked` (только изменённые файлы — слабее).
- `PyCG` — peer-reviewed генератор графа вызовов, но **сломан на новых Python
  с ~апреля 2025** → не брать.
- Идиоматика «что задето» из больших систем: `bazel query
  'rdeps(tests(//...), //path:file)'`, `allpaths`, `somepath`.

### 6.3 C / C++ (владелец: «для C — Clang»)

Порядок выбора **под нашу ситуацию** (Windows-машина владельца, игра как
фактовое дерево, C-правки не в активной линии):

1. **Serena через clangd** — практичный выбор. LSP-точный `find_symbol` /
   `find_referencing_symbols` / `get_diagnostics_for_file` без индексации на
   часы. Для лучших результатов по C/C++ нужен `compile_commands.json`.
2. **clang-query / clang-tidy AST-матчеры** — «все вызывающие `f`» точным
   матчером. Требует `compile_commands.json`. Хорошо скриптуется, дёшево.
3. **cppgraph** (`github.com/rakiz/cppgraph`) — compiler-exact: SCIP через
   `scip-clang`, каждый символ имеет стабильную идентичность (USR/mangled),
   поэтому края точные: перегрузки, `ptr->method()`, шаблоны, виртуальный
   dispatch, без склейки одноимённых. MCP-инструменты `who_calls`,
   `what_it_calls`, `find_references`, `impact_of`, `path`,
   `base_classes`/`subclasses`, `hotspots` + CLI. **Но тяжело:** нужен
   `compile_commands.json`; индексация ~20 мин на 6000 TU (14 ядер) и **~4 ч
   на 6482 TU (8 ядер)**; компиляция scip-clang ~25–60 мин (Docker);
   **Windows → только WSL2**; Intel Mac → только emulate; установка строго в
   `${XDG_DATA_HOME:-$HOME/.local/share}/cppgraph/repo` с отдельным venv
   (нельзя `pip install cppgraph` в venv проекта). Брать только если появятся
   серьёзные C/C++-правки.
4. Легковесные/приблизительные: `cflow --cpp`, `egypt`
   (`gcc -fdump-rtl-expand` → dot), Doxygen+Graphviz (call graph И called-by,
   обязательно включить undocumented entries), `cppcheck --callgraph`
   (экспериментально), `clang++ -S -emit-llvm | opt -analyze -dot-callgraph`,
   CodeViz, cally.
5. Path-sensitive/дефекты (не impact, а качество): Clang Static Analyzer /
   `scan-build`, Frama-C, Infer, CodeQL, joern, QVoG, `gcc -fanalyzer` (≥12).

### 6.4 Универсальные (если нужен один сервер на все языки)

- **Serena** (oraios) — MCP, LSP-бэкенд, 40+ языков (Python, TS/JS, C/C++
  через clangd, Go, Rust, Java, C#, Ruby, PHP, Kotlin, Swift, Bash, …).
  Инструменты: `find_symbol`, `symbol_overview`, `find_referencing_symbols`,
  `find_declaration`, `find_implementations`, `get_diagnostics_for_file`,
  `replace_symbol_body`, `insert_after_symbol`, `rename_symbol`, `safe delete`,
  `activate_project`, `write_memory`/`read_memory`. Полиглот-репо держит
  несколько LSP параллельно. Монорепо: `additional_workspace_folders` в
  `project.yml` (**только TypeScript**). `serena project index` перед первой
  сессией, чтобы LSP не был холодным. Запуск:
  `uv tool install -p 3.13 serena-agent && serena init` или
  `uvx --from git+https://github.com/oraios/serena serena start-mcp-server`.
  Дашборд `http://localhost:24282/dashboard`.
  **Лицензия: данные расходятся** — PyPI/каталоги пишут MIT, зеркало репо
  показывает GPL-3.0-or-later. Проверить в самом репо перед включением.
- **tree-sitter-analyzer (TSA)** — MCP + CLI, 13 языков с полным call-graph
  (Python, Java, Go, JS, TS, C, C++, Rust, C#, Swift, Kotlin, Ruby, PHP).
  Ключевое отличие — **family-gated разрешение имён**: не связывает
  `sorted()` из Python со `func sorted` из Swift (замер: 745 cross-language
  mis-wires у CodeGraph против 6 у TSA при 3× большем числе рёбер).
  Есть ровно то, что нам надо: `--affected FILE...` (затронутые тесты),
  `nav action=impact` (blast radius + risk score), `nav action=callers/callees`,
  `action=call_path`, `edit action=safe|guard` (**отказывает рискованную
  правку до её совершения**), `edit action=constraints` (DSL «модуль A не
  импортирует B»), `edit action=pr` (AST-diff + blast radius),
  `health action=dead|matrix|heatmap`, `nav action=lineage` (частота изменений
  символа по git), `project action=journal` (журнал архитектурных решений
  между сессиями). Вывод TOON (~вдвое компактнее JSON), verdict envelopes
  (SAFE/CAUTION/UNSAFE/…), `agent_summary` с подсказкой следующего шага в
  каждом ответе. Установка:
  `curl -fsSL https://raw.githubusercontent.com/aimasteracc/tree-sitter-analyzer/main/install.sh | bash`,
  проверка `tree-sitter-analyzer --doctor`, индекс `--full-index`.
- **Codebase-Memory** (arXiv 2603.27277, open source) — один статически
  слинкованный C-бинарь, ноль зависимостей, tree-sitter на 66 языках, граф в
  SQLite, 14 MCP-инструментов (call-path tracing, **impact analysis**, hub
  detection), субмиллисекундные запросы, инкрементальное переиндексирование по
  file-watch + content-hash, 6-стратегийное разрешение вызовов, Louvain для
  сообществ. Масштабируется до ядра Linux (2.1 M). Ценен как **образец
  архитектуры** и как вариант «один бинарь на всё».
- **aider repo map** — образец «контекстной подачи» графа в модель: tree-sitter
  + `tags.scm` (def/ref) → networkx **персонализированный PageRank** (посев =
  идентификаторы из задачи + файлы в работе) → токен-бюджет ~1024 →
  SQLite-кэш неизменённых файлов → 130+ языков, без эмбеддингов и сети
  (`aider/repomap.py`: `get_ranked_tags_map` 365–485, `rank_tags` 487–577,
  `to_tree` 579–699). Эту идею (посев из задачи + изменённых путей, бюджет,
  кэш) стоит применить к тому, **что именно** мы кладём в `pre_llm_call`.
- В экосистеме hermes уже есть `oh-my-hermes/src/codegraph/scanner.py`: граф
  импортов построен, но ранжируется по совпадению терминов и **не подключён к
  handoff**; запрос `hermes-agent#535` просит то же на хосте. Подключать, а не
  переписывать.

---

## 7. Побочная находка, важная для линии C1 (браузерный прогон)

hermes умеет водить **наш живой Chrome** сам:

```yaml
browser:
  cloud_provider: local
  cdp_url: "http://localhost:9222"     # или BROWSER_CDP_URL в ~/.hermes/.env
  cdp_stay_put: true                   # PR #112937: «не уводить» вкладку
  cdp_endpoints:                       # именованные сессии
    primary:
      url: http://127.0.0.1:9222
      stay_put: true
  dialog_policy: must_respond          # must_respond | auto_dismiss | auto_accept
  dialog_timeout_s: 300
  inactivity_timeout: 120
  command_timeout: 30
```

- `/browser connect` — интерактивная slash-команда CLI (не диспетчеризуется
  gateway); `connect`, `connect ws://host:port`, `status`, `disconnect`.
  Сам находит Chrome/Chromium/Brave/Edge, запускает с
  `--remote-debugging-port=9222` (detached), ждёт порт до 5 с, иначе печатает
  ручные инструкции. **Инжектирует в модель сообщение, что браузер живой**
  («будь внимателен к открытым вкладкам, спрашивай прежде чем уйти»).
- Порядок разрешения: `BROWSER_CDP_URL` → именованный `cdp_endpoints` →
  `browser.cdp_url`.
- `browser_cdp` — **сырой CDP passthrough**, escape hatch для всего, что не
  покрыто остальными инструментами: диалоги, eval в области iframe,
  cookie/network, любой CDP-глагол. Доступен только когда эндпоинт достижим на
  старте сессии.
- **Chrome 136+ игнорирует `--remote-debugging-port` для каталога профиля по
  умолчанию** — флаг молча не применяется, `/browser connect` получает
  connection refused. Требуется отдельный `--user-data-dir`
  (например `$HOME/.hermes/chrome-debug`). **Наш `OFFLINE-BROWSER.md` уже
  предписывает `--user-data-dir=C:\chrome-cdp` — инструкция верна.**
- **WSL2 + Windows Chrome: документация прямо рекомендует MCP вместо
  `/browser connect`** — современный live-debugging Chrome часто暴露
  host-local эндпоинт, недоступный из WSL как классический 9222. Если hermes
  у владельца в WSL2, а Chrome в Windows — нужен Windows-side browser MCP
  (например `chrome-devtools-mcp` через `cmd.exe`/`powershell.exe`; это же
  рекомендация из FAQ hermes). **Это надо проверить до J8.**
- `cdp_stay_put` + Bot Screen lease (`human_has_control`) — механизм, которым
  можно запретить агенту уводить вкладку у человека. Прямое соответствие
  нашему запрету «не запускать игру, если пользователь уже в ней».

Следствие для C1: наш `node dist/run_offline.mjs` остаётся **приёмочным**
инструментом (детерминированный, с evidence-файлом), но сам hermes способен
наблюдать живой мир через `browser_snapshot`/`browser_console`/`browser_cdp`
без нашего моста. Это не отменяет критерий приёмки, а даёт второй канал.

---

## 8. Что решено / что нужно от владельца

### Решено (не требует обсуждения)

1. `hermes/hooks/hooks.json` — удалить как несовместимый; замена = блок
   `hooks:` в `~/.hermes/config.yaml` + плагин в `.hermes/plugins/woof-guard/`.
2. Включить `tool_loop_guardrails.hard_stop_enabled: true` и пороги из §3
   **до** написания своего guard'а.
3. Matcher'ы переписать под реальные имена инструментов (§2).
4. Контент всех хуков перевести с замороженной `woof-agent/` на `woof-ts/`.
5. Статические правила → `register_system_prompt_section` (≤4000 знаков);
   динамика → `pre_llm_call` → `{"context": …}`.
6. Impact-набор: TS = `vitest-affected` + `tsc --noEmit`; Python =
   `pytest-impacted` + `import-linter`; C = Serena/clangd, при необходимости
   clang-query. Свой сканер не пишем.
7. `fullSuiteTriggers` обязан включать `evidence/`, `package.json`,
   `tsconfig*.json`, `vite.config.*`, lockfiles, `tools/setup_game.sh`,
   `.env*` и параметры `WOOF_PARAMS` — граф импортов их не видит.

### Вопросы владельцу

- **Q1. Где размещать guard:** project-level `.hermes/plugins/woof-guard/`
  (в репо, версионируется, нужен `HERMES_ENABLE_PROJECT_PLUGINS=true` +
  `plugins.enabled`) или user-level `~/.hermes/plugins/` (работает сразу, но
  вне репо)? Рекомендация: **в репо** + скрипт установки
  `tools/install_hooks.sh`, который печатает обе переменные и проверяет их.
- **Q2. Брать ли `tool-loop-guard` как зависимость** (§4) или 40 своих строк
  с тестами? Рекомендация: свои строки — нам нужен `repo_state_hash` и
  JSONL-журнал, которых в библиотеке нет, а окно тривиально.
- **Q3. Serena или TSA как MCP-сервер?** Serena — LSP-точность, 40+ языков,
  умеет писать (нужен `trust: untrusted`), лицензия неоднозначна. TSA —
  13 языков, `--affected`, `edit action=safe/guard`, constraint DSL, TOON,
  read-only по духу. Рекомендация: **начать с TSA** (он ближе к задаче
  «impact-набор и безопасна ли правка»), Serena — вторым, если понадобится
  symbol-level редактирование.
- **Q4. hermes на машине владельца — нативный Windows или WSL2?** От этого
  зависит §7 (WSL2 + Windows Chrome → MCP вместо `/browser connect`) и формат
  путей в `command:`.

---

## 9. Источники

- Hooks: `hermes-agent.nousresearch.com/docs/user-guide/features/hooks`
  (+ зеркало `github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/hooks.md`)
- Plugins: `…/docs/user-guide/features/plugins`; developer guide
  `…/docs/developer-guide/plugins` (манифест v2, отладка discovery)
- Toolsets/tools: `…/docs/reference/toolsets-reference`,
  `…/docs/reference/tools-reference/`
- MCP: `…/docs/user-guide/features/mcp.md`,
  `…/docs/reference/mcp-config-reference.md`; issue #342, #690, #18074
- Browser/CDP: `…/docs/user-guide/features/browser`; PR #1549
  (`/browser connect`), issue #5507 (`browser.cdp_url`), PR #112937
  (`cdp_endpoints`, `cdp_stay_put`); `…/docs/reference/environment-variables.md`
- Guardrails: `agent/tool_guardrails.py`; issues #112535, #34610, #46804,
  #481, #120415(openclaw); PR #101833, #85352, #106428, #67538;
  `hermes hooks test` баг #115968
- Loop-guard prior art: `RightNow-AI/openfang` (`loop_guard.rs`),
  PyPI `tool-loop-guard` (`MukundaKatta/tool-loop-guard`),
  `pi.dev/packages/pi-loop-police`, `data-fair/agents` PR #56,
  particula.tech «Stop AI Agents Looping on the Same Failed Tool Call»,
  evener #94, agent-zero #1690, LangChain #36139
- TS impact: `github.com/craigvandotcom/vitest-affected` (+ их skill
  `vitest-plugin-dev`), dev.to «Why `vitest --changed` misses some tests»
  (testpick)
- Python impact: `pytest-impacted`, `grimp`/`import-linter`, `tach`,
  `pyan3` (PyPI 2.6.x), `code2flow`, `PyCG` (сломан), bazel `rdeps`
- C/C++: `github.com/rakiz/cppgraph` (README: Phase A/B, timings, WSL2),
  clang-query/clang-tidy, scan-build, cppcheck `--callgraph`, cflow, egypt,
  Doxygen, `-emit-llvm | opt -analyze -dot-callgraph`
- Универсальные: Serena (`github.com/oraios/serena`, `serena-agent` на PyPI),
  `github.com/aimasteracc/tree-sitter-analyzer`,
  arXiv 2603.27277 «Codebase-Memory», `aider/repomap.py`,
  `oh-my-hermes/src/codegraph/scanner.py`, `hermes-agent#535`

Атрибуция: производный артефакт проекта MaleCNS, CC BY 4.0.
