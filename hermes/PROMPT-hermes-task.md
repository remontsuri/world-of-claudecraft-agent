# ПРОМПТ ДЛЯ HERMES — сделать анти-повторные хуки (Windows 11, автономно)

Этот файл самодостаточен. Все факты ниже проверены по документации и трекеру
hermes (2026-09-19/20) и по текущему состоянию репозитория. Исследовать заново
ничего не нужно. Текст системной секции (§8) и каркас плагина (§9) встроены —
внешние файлы читать не обязательно.

---

## 1. ЗАДАЧА

Сделать так, чтобы агент в этом репозитории:

1. не повторял одно и то же действие (включая циклы вида A,B,A,B);
2. не «тупил» из-за устаревшего контекста — каждый ход получал фактическое
   состояние репо из хука, а не вспоминал его;
3. прогонял только затронутые проверки, а не всё подряд.

Средства: конфиг hermes + плагин + shell-хуки + готовые сторонние инструменты.
**Писать свой AST-сканер, свой граф импортов или свой анализатор зависимостей
запрещено** — всё нужное уже существует (§7).

## 2. ОКРУЖЕНИЕ (дано владельцем)

- ОС: **Windows 11**.
- Hermes установлен локально: **`D:/.hermes/hermes-agent`**.
  Значит `HERMES_HOME = D:/.hermes`, и пути такие:
  | Что | Где |
  |---|---|
  | конфиг | `D:/.hermes/config.yaml` |
  | секреты (env) | `D:/.hermes/.env` |
  | user-level плагины | `D:/.hermes/plugins/<name>/` |
  | gateway-хуки | `D:/.hermes/hooks/<name>/` |
  | shell-хуки (соглашение) | `D:/.hermes/agent-hooks/` |
- Путь к репозиторию **не задан**. Определи его сам и дальше используй как
  `<REPO>`:
  ```
  git rev-parse --show-toplevel
  ```
  Если команда выполнена не из репозитория — найди его (признаки: каталоги
  `woof-ts/`, `hermes/`, `knowledge/`, `archive/`, файл `AGENTS.md`) и объяви
  найденный путь в первом же отчёте. Все пути в конфигах пиши **прямыми
  слэшами**: `D:/…`, не `D:\…`.
- Активная линия: **`<REPO>/woof-ts/`** — TypeScript, мост + агент,
  самостоятельно играющий в World of ClaudeCraft.

## 3. ЖЁСТКИЕ ОГРАНИЧЕНИЯ (нарушение = провал задания)

1. Ветка — только `backup`. Никогда `push --force`. Никогда не трогать `master`.
2. Коммит — только по явной команде владельца «коммит». Пуш — только по команде
   «пуш». До команды — работа в дереве.
3. Секреты и токены — только из env (`D:/.hermes/.env`). Никогда в файлы,
   никогда в `.git/config`, никогда в переписку.
4. Не трогать `game/` (симлинк на фактовое дерево игры) и исходники игры.
5. Не убивать процессы `hermes-agent`, `hermes-gateway`. На Windows это значит:
   никакого `taskkill /IM python.exe`, `taskkill /F /IM node.exe`,
   `Stop-Process -Name python` — убьёт и агента, и игру.
6. `archive/` — только чтение: не удалять, не выносить, не переписывать выводы.
   Новые факты — датированной строкой в `archive/fly-line/README.md`.
7. Замороженные линии `woof-agent/` (Java) и `archive/fly-line/` — не править.
8. Пункт, помеченный «✅», закрыт: не переделывать и не «улучшать».
9. Никаких молчаливых фолбэков: проверка не запустилась — это FAIL, а не
   «пропущено».
10. Пороги объявлять ДО измерения.
11. Русский язык, прямо, без воды. На прямой вопрос отвечать сразу в чате, не
    уходя в молчаливое написание файлов.
12. Не патчить ядро hermes (`D:/.hermes/hermes-agent/**`, в частности
    `agent/tool_guardrails.py`) — только конфиг, плагины, хуки.
13. Не включать `hooks_auto_accept: true`. Не ставить MCP-сервер с
    `trust: full`. Не добавлять зависимости без разрешения владельца.

## 4. ПРОВЕРЕННЫЕ ФАКТЫ О HERMES (не переспрашивать)

### 4.1 Реальные имена инструментов

`terminal`, `process` · `read_file`, `write_file`, `patch`, `search_files` ·
`web_search`, `web_extract` · `browser_navigate`, `browser_snapshot`,
`browser_click`, `browser_type`, `browser_press`, `browser_scroll`,
`browser_back`, `browser_console`, `browser_get_images`, `browser_vision`,
`browser_cdp`, `browser_dialog` · `execute_code` · `delegate_task` ·
`skills_list`, `skill_view`, `skill_manage` · `todo`, `memory`, `clarify`,
`session_search`, `cronjob` · MCP-инструменты как `mcp__<server>__<tool>`.

**Инструмента `edit` НЕ существует.** Правка файла — это `patch` (fuzzy,
9 стратегий, возвращает unified diff, сам гоняет синтаксические проверки) и
`write_file` (полная перезапись; отказывается писать, если файл не прочитан в
этой задаче или изменился на диске).

`browser_cdp` и `browser_dialog` регистрируются **только** если CDP-эндпоинт
достижим на старте сессии.

### 4.2 Четыре системы хуков

| Система | Регистрация | Расположение | Блокирует вызов | Инжектирует контекст |
|---|---|---|---|---|
| Gateway | `HOOK.yaml` + `handler.py` | `D:/.hermes/hooks/<name>/` | нет | нет |
| **Plugin** | `ctx.register_hook()` | `D:/.hermes/plugins/<name>/` или `<REPO>/.hermes/plugins/<name>/` | да (`pre_tool_call`) | да (`pre_llm_call`) |
| Shell | блок `hooks:` в `config.yaml` | по соглашению `D:/.hermes/agent-hooks/` | да | да |
| Outbound | `hooks.outbound:` | — | нет | нет |

События (`VALID_HOOKS`): `pre_tool_call`, `post_tool_call`, `pre_llm_call`,
`post_llm_call`, `pre_verify`, `on_session_start`, `on_session_end`,
`on_session_finalize`, `on_session_reset`, `subagent_start`, `subagent_stop`,
`pre_api_request`, `transform_*`, `pre_transcription`.

**Shell-хук, stdin (JSON):**
```json
{"hook_event_name":"pre_tool_call","tool_name":"terminal",
 "tool_input":{"command":"git push --force"},"session_id":"…","cwd":"…",
 "extra":{"task_id":"…","tool_call_id":"…"}}
```

**Shell-хук, stdout (JSON), пустой вывод = no-op:**
- блок: `{"action":"block","message":"…"}` или compat
  `{"decision":"block","reason":"…"}`
- подмена аргументов: `{"action":"modify","args":{…}}`
- `pre_llm_call`: `{"context":"…"}` — вводится в **USER** message, не в
  системный (так не ломается KV-кэш)
- `pre_verify`: `{"action":"continue","message":"…"}`; в payload есть
  `changed_paths` — свой `git diff` дёргать не обязательно

`matcher` (регулярка) — только для `pre_tool_call`/`post_tool_call`.
`fail_closed` (алиас `failClosed`) — только для `pre_tool_call`.
`timeout` по умолчанию 60, максимум 300.

Plugin-хуки регистрируются раньше shell-хуков → при ничьей Python-block
побеждает. Первый валидный block выигрывает.

### 4.3 Windows-специфика shell-хуков (критично)

- `command` разбирается через `shlex.split` и запускается с **`shell=False`**:
  - нужен **абсолютный путь к исполняемому** (голое `python` может не
    разрешиться); путь узнать так: `python -c "import sys;print(sys.executable)"`;
  - **запрещены** `&&`, `|`, `>`, `%VAR%`, `~`;
  - `shlex.split` по умолчанию в POSIX-режиме → **обратный слэш съедается**;
    все пути писать прямыми слэшами.
- Кодировка: в `.cmd`-обёртке `set PYTHONUTF8=1` и `set PYTHONIOENCODING=utf-8`,
  в Python — `sys.stdout.reconfigure(encoding="utf-8")`. Эмодзи из сообщений
  хуков убрать, кириллицу оставить.
- `.cmd` обязан пробрасывать stdin в Python и stdout наружу **без собственного
  текста** (иначе JSON-ответ ломается). `@echo off` обязателен.
- Line endings: создать в корне репо `.gitattributes`, если его нет:
  ```
  * text=auto eol=lf
  *.cmd text eol=crlf
  *.ps1 text eol=crlf
  *.bat text eol=crlf
  ```
- env-переменная для project-level плагинов задаётся **до** запуска hermes:
  PowerShell `$env:HERMES_ENABLE_PROJECT_PLUGINS="true"` (текущая сессия) или
  `setx HERMES_ENABLE_PROJECT_PLUGINS true` (новый терминал увидит после
  перезапуска).

### 4.4 Плагины opt-in — два обязательных условия

1. Project-local плагины в `<REPO>/.hermes/plugins/` отключены по умолчанию:
   нужен `HERMES_ENABLE_PROJECT_PLUGINS=true` до запуска hermes.
2. **Все** плагины opt-in: имя должно быть в `plugins.enabled`
   (`D:/.hermes/config.yaml`) или `hermes plugins enable <name>`.

Раскладка: `<plugins>/<name>/plugin.yaml` + `__init__.py` с `register(ctx)`.
Плоско или максимум один уровень категории — глубже игнорируется.

Поля манифеста v2 (все опциональны, неизвестные игнорируются с warning):
`manifest_version` (макс. 2), `api_version`, `requires_plugins`,
`python_dependencies` (только декларация — hermes сам не ставит),
`config_schema` (ключи в `plugins.entries.<id>.settings`), `license`,
`homepage`, `tags`, `requires_env`, `capabilities`.

Отладка discovery: (а) не в `plugins.enabled`; (б) неправильная раскладка;
(в) нет `__init__.py` с `register(ctx)`; (г) не тот `kind`.

### 4.5 Системный промпт

`ctx.register_system_prompt_section(id, str|callable, position="after_memory",
max_chars=4000)` — ≤4000 знаков на секцию, суммарно 8000 знаков / 32 секции,
ставится один раз на сессию и **замораживается при компрессии контекста**.
Поэтому статика — туда, динамика — в `pre_llm_call`.

### 4.6 Встроенная защита от повторов

- `tool_loop_guardrails.hard_stop_enabled` **по умолчанию false** — это главная
  причина «тупит»: зафиксировано ~500 идентичных вызовов подряд (issue #112535).
- Ключ `tool_repetition` на части версий **принимается конфигом, но no-op**
  (issues #34610, #46804). Проверить на своей версии и записать факт.
- PR #101833: `reset_for_turn()` обнулял счётчики → повторы через ходы не
  накапливались.
- PR #106428 (мержнут): stall guard ловит мульти-вызовные циклы, а не только
  соседние повторы.
- PR #85352: считать по **сигнатуре вызова**, а не по хешу результата —
  компрессия подменяет тело повтора заглушкой `[Duplicate tool output — same
  content as a more recent call]`. Из ревью того же PR два обязательных
  исключения: (а) легитимный поллинг — чтение файла, который меняет внешний
  процесс; (б) новый пользовательский ход, легитимно перечитывающий тот же файл.
- Баг #115968 (0.21.3): `hermes hooks test` **не показывает решение при ошибке
  или таймауте** хука. Пустой вывод не означает «хук ничего не решил» —
  проверять вызовом хука напрямую.

### 4.7 Что сейчас сломано в репозитории (проверено по файлам)

- `hermes/hooks/hooks.json` несовместим ни с одной системой хуков: выдуманные
  события (`session_start`, `pre_tool`, `task_end` вместо `on_session_start`,
  `pre_tool_call`, `on_session_end`) и выдуманная форма stdin
  (`{"event","cwd","tool","command","paths","task"}`). Хуки не срабатывают.
- `hermes/hooks/guard.sh` читает именно эти несуществующие поля (`tool`,
  `command`, `paths`) — блокировки не работают, даже если хук запустить.
- `hermes/hooks/session_start.sh`, `task_end.sh`, `hermes/README.md`,
  `hermes/skills/woc-master-goal/SKILL.md` ведут в замороженную Java-линию
  `woof-agent/`.
- В `hermes/hooks/win/` есть только `guard.cmd`, `session_start.cmd`,
  `task_end.cmd` — под новые события обёрток нет.
- `hermes/hooks/selftest.sh` — 17 проверок, новый контракт не покрывает.
- Анти-повторного хука нет.

### 4.8 Особенности сборки в `woof-ts/` (грабли, не повторять)

- Перед любой сборкой: `bash tools/setup_game.sh` — симлинк `game/` и
  `node_modules/` стираются между ходами.
- Гейт: `bash tools/check_all.sh`, шаги 0–8. `NO_COLOR=1` обязателен (ANSI
  попадает между `Tests` и `26 passed`).
- `set -o pipefail` + `grep -q` с vitest = ложный провал (SIGPIPE 141): вывод в
  переменную, затем `[[ =~ ]]`.
- `grep -i` в локали C ломает кириллицу → использовать `grep -qF`.
- Параметры агента — только через `WOOF_PARAMS=<file.json>`.
- В vitest нет `--reporter=basic`; динамический `import()` отсутствующего `.ts`
  ломает tsc → `it.skipIf(!existsSync(path))`.

## 5. ПОРЯДОК РАБОТЫ

Один пункт за ход. По каждому: (а) назвать стоп-условие, (б) сделать минимальную
правку, (в) прогнать проверки, (г) заполнить таблицу §10. Не переходить дальше,
пока таблица не заполнена.

**П0. Разведка (ничего не менять).** Заполнить таблицу:

| Что | Как узнать |
|---|---|
| Путь к репо (`<REPO>`) | `git rev-parse --show-toplevel` |
| Версия hermes | `hermes --version` |
| Абсолютный путь Python | `python -c "import sys;print(sys.executable)"` |
| Git доступен | `git --version` |
| node / npm | `node -v` · `npm -v` |
| Версия Vitest в `woof-ts/` | `npm ls vitest` |
| Bash (Git Bash) | `bash --version` |
| Текущий `plugins.enabled` | `hermes plugins list` |
| Текущие хуки | `hermes hooks list` |
| Работает ли `tool_repetition` | объявить 2/3 и проверить срабатывание |

Стоп-условие: таблица заполнена фактическими значениями, объявлен `<REPO>`.
Если bash отсутствует — гейт `check_all.sh` не запустится, это надо сообщить
сразу, не в конце.

**П1. Включить встроенную защиту.** Дополнить `D:/.hermes/config.yaml`
(сначала прочитать, потом `patch`, не затирать существующее):

```yaml
tool_loop_guardrails:
  warnings_enabled: true
  hard_stop_enabled: true
  non_interactive_hard_stop_enabled: true
  warn_after: {exact_failure: 2, same_tool_failure: 3, idempotent_no_progress: 2, tool_repetition: 2}
  hard_stop_after: {exact_failure: 3, same_tool_failure: 5, idempotent_no_progress: 3, tool_repetition: 3}
  loop_caps: {max_web_searches: 20, max_subagents: 10}
agent:
  max_turns: 40
  budget_warning_ratio: 0.75
```

Стоп-условие: чтение файла подтверждает `hard_stop_enabled: true`; в отчёте
зафиксировано, срабатывает ли `tool_repetition` на этой версии.

**П2. Плагин `woof-guard`.** Создать `<REPO>/.hermes/plugins/woof-guard/`:
`plugin.yaml` + `__init__.py` с `register(ctx)`. Реализовать по §6, §8, §9.
Журнал — `<REPO>/.hermes/journal.jsonl` (каталог создавать при старте).
Стоп-условие: `hermes plugins list` показывает `woof-guard`; после
`HERMES_ENABLE_PROJECT_PLUGINS=true` и `hermes plugins enable woof-guard`
команда `hermes hooks list` показывает зарегистрированные события.

**П3. Shell-хуки как второй контур (переносимость + Windows).** В
`<REPO>/hermes/hooks/`:
- общий модуль `woof_guard_core.py` — вся логика §6 (один источник истины для
  плагина и shell-хуков, чтобы поведение не разъезжалось);
- `guard.py` + `win/guard.cmd` — блокировки из §3 (force-push, убийство
  hermes-*, правка `game/`, тяжёлые файлы, `taskkill`); читать
  `tool_name`/`tool_input`, а не `tool`/`command`/`paths`;
- `repeat_guard.py` + `win/repeat_guard.cmd` — алгоритм §6 поверх общего модуля;
- `context.py` + `win/context.cmd` — `pre_llm_call` → `{"context": …}` по §9.2;
- `impact.py` + `win/impact.cmd` — `pre_verify`, берёт `changed_paths` из
  payload и отдаёт команды impact-набора (§7).
Удалить `hooks.json`; вместо него создать `<REPO>/hermes/config.hermes.yaml` —
готовый к вставке блок `tool_loop_guardrails` + `hooks` + `mcp_servers` +
`plugins.enabled`, все пути прямыми слэшами. Обновить `hermes/hooks/README.md`
под реальный контракт. Создать `.gitattributes` (§4.3).

Шаблон блока `hooks:`:
```yaml
hooks:
  pre_tool_call:
    - matcher: "^(terminal|process|write_file|patch|execute_code|delegate_task)$"
      command: "<REPO>/hermes/hooks/win/guard.cmd"
      timeout: 10
      fail_closed: true
    - matcher: "^(terminal|process|write_file|patch|execute_code|delegate_task|read_file|search_files)$"
      command: "<REPO>/hermes/hooks/win/repeat_guard.cmd"
      timeout: 10
      fail_closed: true
  pre_llm_call:
    - command: "<REPO>/hermes/hooks/win/context.cmd"
      timeout: 15
  pre_verify:
    - command: "<REPO>/hermes/hooks/win/impact.cmd"
      timeout: 60
hooks_auto_accept: false
```

Стоп-условие: прямой вызов каждого хука с синтетическим JSON на stdin
возвращает валидный JSON-ответ (проверять именно прямым вызовом — см. баг
#115968 в §4.6), и `hermes hooks list` показывает все четыре записи.

**П4. Impact-слой.** В `<REPO>/woof-ts/`: `npm install -D vitest-affected`,
подключить в `vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';
import { vitestAffected } from 'vitest-affected';

export default defineConfig({
  plugins: [vitestAffected({
    ref: 'backup',
    verbose: true,
    statsFile: '.vitest-affected/stats.jsonl',
    fullSuiteTriggers: [
      'evidence/', 'tools/setup_game.sh',
      /^package\.json$/, /^tsconfig.*\.json$/, /^vite\.config\./,
      /^pnpm-lock\.yaml$/, /^\.env/, /WOOF_PARAMS/,
    ],
    staleCacheDays: 14,
    maxSelectiveRuns: 50,
  })],
  test: { include: ['tests/**/*.test.ts'] },
});
```

`fullSuiteTriggers` обязан включать всё, что граф импортов **не видит**, но что
ломает прогон: `evidence/`, `package.json`, `tsconfig*.json`, `vite.config.*`,
lockfiles, `tools/setup_game.sh`, `.env*`, файлы параметров `WOOF_PARAMS`.
Первый прогон — теневой: `VITEST_AFFECTED_SHADOW=1` (прогоняет всё и логирует,
что **выбрало бы**), сравнить выбор с полным прогоном. Kill switch —
`VITEST_AFFECTED_DISABLED=1`. Требует Vitest ≥ 3.1.0 (хук `configureVitest`).
`impact.py` для Python отдаёт `pytest-impacted` + `lint-imports` (§7).

Стоп-условие: `bash tools/check_all.sh` зелёный (шаги 0–8) **и** теневой прогон
показал, что impact-набор не меньше ожидаемого.

**П5. Починить устаревшее.** `hermes/README.md`,
`hermes/skills/woc-master-goal/SKILL.md`, контент `on_session_start`: активная
линия — `woof-ts/`, заморожены `woof-agent/` и `archive/fly-line/`.
Стоп-условие: поиск `woof-agent` в `hermes/` не находит его как активную линию
(упоминание как замороженной — можно).

**П6. Самопроверка.** Расширить `hermes/hooks/selftest.sh` **и** добавить
кроссплатформенный `hermes/hooks/selftest.py` (bash на Windows может
отсутствовать). Покрыть: форму stdin, имена событий, имена инструментов, оба
формата block, `fail_closed`, и алгоритм §6 на синтетических журналах —
одиночный повтор, ping-pong A,B,A,B, цикл A,B,C, реально новый результат,
смена хода, exempt, read-only пороги. Обновить ожидаемое число проверок в доках.
Стоп-условие: оба selftest зелёные, число в доках совпадает с фактическим.

**П7. Отчёт и остановка.** Таблица §10 по всем пунктам, список созданных и
изменённых файлов, и что нужно от владельца: подтверждение `<REPO>`, версия
hermes, факт по `tool_repetition`, разрешение на установленные зависимости.
**Не коммитить и не пушить без команды.**

## 6. АЛГОРИТМ REPEAT-GUARD (реализовать точно так)

```
сигнатура = sha256(tool_name + canonical_json(args) + repo_state_hash)[:16]
  canonical_json: sort_keys=True, separators=(",",":"), пути нормализованы
                  (слэши вперёд, диск Windows в нижнем регистре)
  repo_state_hash: sha256(git status --porcelain + git diff --stat),
                   при ошибке git — "unknown" (и по состоянию НЕ блокировать)

журнал: <REPO>/.hermes/journal.jsonl (append) + скользящее окно W=20 в памяти

правила по возрастанию жёсткости:
 1. EXEMPT = {process, todo, memory, clarify, session_search, browser_snapshot}
    -> только запись в журнал, без счёта (легитимный поллинг/статус)
 2. READ-ONLY = {read_file, search_files, web_search, web_extract,
    browser_console, browser_get_images} -> пороги мягче: warn 4, block 8,
    и блок только если REREAD_RATIO >= 0.4 (доля перечитываний НЕизменённых
    файлов в окне 10)
 3. MUTATING = {terminal, write_file, patch, execute_code, delegate_task,
    browser_navigate, browser_click, browser_type, browser_press}
    -> warn на 2-м идентичном, block на 3-м
 4. ЦИКЛ ЛЮБОЙ ДЛИНЫ: для w in 1..5 — если последние w вызовов в точности
    равны предыдущим w -> block
 5. сброс счётчика сигнатуры, если результат РЕАЛЬНО новый: хеш результата
    отличается И это не заглушка дедупликации ("[Duplicate tool output")
    И не '{"status":"unchanged"'
 6. сброс окна при смене пользовательского хода (is_first_turn / новый task_id)
 7. при block: вызов НЕ исполняется; возвращается
    {"action":"block","message": ...} с (a) фактом повтора и счётчиком,
    (b) последним результатом (<=200 знаков), (c) требованием сменить
    стратегию — другие аргументы, другой инструмент или объяснить тупик
 8. каждое срабатывание (warn и block) -> строка JSONL:
    {ts, session_id, task_id, tool, sig, count, decision, reason}
```

Пороги объявлены здесь, до внедрения: **warn 2 / block 3 для мутирующих,
warn 4 / block 8 для read-only, окно 20**. Менять только с разрешения владельца.

Запрещено обходить собственный блок: другим инструментом, другим порядком
аргументов, разбиением на части, переименованием файла. Если блокировка кажется
ложной — остановиться и спросить владельца.

## 7. ГОТОВЫЕ ИНСТРУМЕНТЫ (использовать, не переписывать)

**TypeScript:** `vitest-affected` (`npm install -D vitest-affected`) — runtime-граф
импортов, reverse map в `.vitest-affected/graph.json`, BFS от git diff. Никогда
не пропускает тесты молча: ошибка git / битый кэш / неполный граф → полный
прогон с предупреждением. Грабли: re-экспорты лежат в `staticExports`, не в
`staticImports`; oxc-parser pre-1.0 — пинить версию; не вызывать
`project.globTestFiles()`. `tsc --noEmit` остаётся обязательным шагом —
плагин его не заменяет.

**Python:** `pytest-impacted` (`impacted-tests --module=pkg --git-mode=branch
--base-branch=backup`; git diff → astroid → networkx → затронутые тесты;
изменение `uv.lock`/`requirements.txt`/`pyproject.toml` → все тесты) ·
`grimp` + `import-linter` (контракты `layers`/`forbidden`/`independence`/
`protected`/`acyclic_siblings`, вывод нарушенными цепочками,
`lint-imports --contract --no-cache --show-timings`) · `pyan3` ≥ 2.6
(`direction=up|down|both`, `depth=0|1|2|None`, `--paths-from A --paths-to B`,
GPL v2). **`PyCG` сломан на новых Python с ~04.2025 — не брать.**

**C/C++ (если понадобится):** Serena через clangd (нужен
`compile_commands.json`) → clang-query/clang-tidy матчеры «все вызывающие f» →
cppgraph только при серьёзных C-правках (на Windows — исключительно через
WSL2, индексация часы).

**MCP code-intelligence** подключается декларацией в `config.yaml`, не кодом:
`tree-sitter-analyzer` (13 языков с полным call-graph, `--affected FILE`,
`nav action=impact`, `edit action=safe|guard`, constraint DSL, TOON-вывод;
проверка `tree-sitter-analyzer --doctor`, индекс `--full-index`):

```yaml
mcp_servers:
  tsa:
    command: "<абсолютный путь к tree-sitter-analyzer, прямыми слэшами>"
    args: ["mcp"]
    tools: {include: ["*"], prompts: false, resources: false}
    trust: untrusted      # fail-closed для write-инструментов
    lazy: true
    timeout: 120
```

Поля MCP-секции: `tools.include/exclude` — точные имена или glob;
`lazy: true` — поднять процесс при первом вызове; `idle_timeout_seconds` —
ресайкл stdio-сервера; `trust: untrusted` — подтверждение на любой
write-инструмент; интерполяция `${ENV_VAR}` из `D:/.hermes/.env`.
Установку MCP-сервера делать только с разрешения владельца.

**Браузер (для живого прогона; в этом задании — только конфиг):**
```yaml
browser:
  cloud_provider: local
  cdp_url: "http://127.0.0.1:9222"
  cdp_stay_put: true
  dialog_policy: must_respond
  dialog_timeout_s: 300
```
Chrome 136+ **молча игнорирует** `--remote-debugging-port` для каталога
профиля по умолчанию, поэтому запуск только с отдельным профилем:
`chrome.exe --remote-debugging-port=9222 --user-data-dir=D:\chrome-cdp
--no-first-run --no-default-browser-check`.

## 8. ТЕКСТ СИСТЕМНОЙ СЕКЦИИ (3101 знак, вставлять как есть)

```
ПРАВИЛА РАБОТЫ (репозиторий MaleCNS, CC BY 4.0)

1. ЛИНИИ. Активная — woof-ts/ (TypeScript: мост + агент, самостоятельно
играющий в World of ClaudeCraft). ЗАМОРОЖЕНЫ и не трогаются: woof-agent/
(Java-линия) и archive/fly-line/. archive/ — только чтение: не удалять,
не выносить, не переписывать выводы; новые факты — датированной строкой.
Если пункт помечен «✅» — он закрыт, НЕ переделывать и не «улучшать».

2. ЗАПРЕТЫ. Никогда: git push --force; правки ветки master; убийство
процессов hermes-agent/hermes-gateway; правка исходников игры (game/ —
симлинк на фактовое дерево); запуск игры или перезапуск браузера, если
владелец уже в них; window.location.reload() через CDP; перезапуск
моста/агента после правок без команды владельца. Секреты — только из env,
никогда из файлов и не в переписку.

3. ПОВТОРЫ ЗАПРЕЩЕНЫ. Повтор — это идентичное действие при неизменном
состоянии репо. Цикл A,B,A,B — тоже повтор, а не два разных действия.
Перечитывание файла, который никто не менял, — повтор. Если хук заблокировал
вызов: НЕ обходить его (другим инструментом, другим порядком аргументов,
разбиением на части). Прочитай сообщение блока, смени стратегию и скажи
владельцу, что именно ты меняешь. Если считаешь блокировку ложной —
остановись и спроси, не подбирай обход.

4. ПОРЯДОК РАБОТЫ. Один пункт за ход: (а) назови пункт и его стоп-условие —
что именно будет считаться завершением; (б) сделай минимальную правку;
(в) прогони impact-набор проверок, а не «всё подряд»; (г) заполни таблицу
приёмки; (д) только затем переходи к следующему пункту. Перед любой сборкой
в woof-ts/ — bash tools/setup_game.sh (симлинк game/ и node_modules
стираются между ходами).

5. ПРОВЕРКИ. Impact-набор объявляется ДО запуска. Для woof-ts/: tsc --noEmit
+ vitest с плагином vitest-affected (полный гейт — bash tools/check_all.sh,
шаги 0–8; NO_COLOR=1 обязателен). Для Python: pytest-impacted + import-linter.
Не подменять прогон чтением кода и не объявлять успех без вывода инструмента.
Пороги метрик объявляются ДО измерения. Никаких молчаливых фолбэков: если
проверка не запустилась — это ПРОВАЛ, а не «пропущено».

6. ЧЕСТНОСТЬ. Не выдавать предположение за факт. Различать: «проверено
выводом инструмента», «проверено на полигоне», «не проверялось — нужен живой
прогон владельца». Если что-то не сделано — сказать прямо. Не писать
«готово» до зелёного гейта. Коммит и пуш — только по явной команде
«коммит»/«пуш».

7. РАЗРЕШЕНИЯ ВЛАДЕЛЬЦА. Спросить до действия, а не после: удаление файлов,
правка замороженных линий, изменение порогов приёмки, пуш, установка новых
зависимостей, любые операции с токенами.

8. СТОП-УСЛОВИЕ У КАЖДОЙ ОПЕРАЦИИ. Прежде чем вызвать инструмент, знай, при
каком результате ты остановишься. Операция без стоп-условия — это источник
цикла. Не запускать «ещё раз на всякий случай».

9. ФОРМАТ ОТЧЁТА по каждому пункту:
| LAYER | EXPECTED | ACTUAL | STATUS |
Строки — по числу проверок. STATUS: PASS / FAIL / NOT RUN (+ причина).

10. ЯЗЫК И ТОН. Русский, прямо, без воды. На прямой вопрос отвечать сразу,
в чате, не уходя в молчаливое написание файлов. Запись в репо — только
с разрешения.
```

## 9. КАРКАСЫ (довести до соответствия §6)

### 9.1 `plugin.yaml`

```yaml
name: woof-guard
version: 1.0.0
description: Anti-repeat guard, repo-state context, impact-set verification (woof-ts line)
author: MaleCNS (CC BY 4.0)
manifest_version: 2
api_version: 1
python_dependencies: []
config_schema:
  journal_path: {type: str, default: ".hermes/journal.jsonl", description: "JSONL journal (relative to repo root)"}
  window:       {type: int, default: 20, description: "sliding window size"}
  warn_after:   {type: int, default: 2,  description: "identical mutating calls before warn"}
  block_after:  {type: int, default: 3,  description: "identical mutating calls before block"}
license: CC-BY-4.0
tags: [guardrails, woof]
```

### 9.2 `__init__.py`

Каркас ниже покрывает правила 1, 3, 4, 8 из §6. Правила 2 (read-only пороги и
`REREAD_RATIO`), 5 (реально новый результат), 6 (смена хода), 7 (содержимое
сообщения блока) — **дописать обязательно**. Логика должна жить в общем модуле
`woof_guard_core.py`, чтобы shell-хуки использовали тот же код.

```python
import hashlib, json, os, subprocess, sys, time
from collections import deque
from pathlib import Path

WINDOW, WARN_AFTER, BLOCK_AFTER = 20, 2, 3
EXEMPT = {"process", "todo", "memory", "clarify", "session_search", "browser_snapshot"}
MUTATING = {"terminal", "write_file", "patch", "execute_code", "delegate_task",
            "browser_navigate", "browser_click", "browser_type", "browser_press"}

RULES = (Path(__file__).parent / "data" / "section-a.txt").read_text(encoding="utf-8")

def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]

def _repo_root() -> str:
    return os.environ.get("WOOF_REPO") or os.getcwd()

def _repo_state(cwd: str) -> str:
    try:
        a = subprocess.run(["git", "status", "--porcelain"], cwd=cwd,
                           capture_output=True, text=True, timeout=10)
        b = subprocess.run(["git", "diff", "--stat"], cwd=cwd,
                           capture_output=True, text=True, timeout=10)
        return _sha(a.stdout + b.stdout)
    except Exception:
        return "unknown"

def _sig(tool: str, args: dict, state: str) -> str:
    return _sha(json.dumps({"t": tool, "a": args, "s": state},
                           sort_keys=True, separators=(",", ":")))

class Guard:
    def __init__(self, journal: Path):
        self.journal = journal
        self.hist = deque(maxlen=WINDOW)
        self.counts = {}
        self.last_task = None
        journal.parent.mkdir(parents=True, exist_ok=True)

    def cycle(self, w: int) -> bool:
        """последние w вызовов в точности равны предыдущим w — цикл длины w"""
        h = list(self.hist)
        return len(h) >= 2 * w and h[-w:] == h[-2 * w:-w]

    def _log(self, rec: dict) -> None:
        rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self.journal.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def pre(self, tool, args, cwd, session_id, task_id):
        if task_id != self.last_task:      # правило 6: смена хода — сброс окна
            self.last_task, self.hist, self.counts = task_id, deque(maxlen=WINDOW), {}
        if tool in EXEMPT:
            self._log({"session_id": session_id, "task_id": task_id, "tool": tool,
                       "decision": "exempt"})
            return None
        sig = _sig(tool, args, _repo_state(cwd))
        n = self.counts.get(sig, 0) + 1
        self.counts[sig] = n
        self.hist.append(sig)

        decision, reason = None, None
        for w in (1, 2, 3, 4, 5):
            if self.cycle(w):
                decision = "block"
                reason = (f"Обнаружен цикл длины {w}: последние {w} вызовов в "
                          f"точности повторяют предыдущие {w}. Смени стратегию — "
                          f"другие аргументы, другой инструмент, или объясни "
                          f"владельцу, в чём тупик.")
                break
        if decision is None and tool in MUTATING and n >= BLOCK_AFTER:
            decision = "block"
            reason = (f"{tool}: {n}-й идентичный вызов при неизменном состоянии "
                      f"репо. Не исполнено. Измени аргументы, возьми другой "
                      f"инструмент или объясни владельцу, в чём тупик.")
        elif decision is None and tool in MUTATING and n >= WARN_AFTER:
            decision = "warn"
            reason = f"{tool}: {n}-й идентичный вызов. Ещё один — и будет блок."

        self._log({"session_id": session_id, "task_id": task_id, "tool": tool,
                   "sig": sig, "count": n, "decision": decision or "allow",
                   "reason": reason})
        if decision == "block":
            return {"action": "block", "message": reason}
        return None

_guard = None

def register(ctx):
    global _guard
    root = Path(_repo_root())
    _guard = Guard(root / ".hermes" / "journal.jsonl")

    def on_pre_tool(tool_name=None, args=None, task_id=None, session_id=None,
                    cwd=None, **kw):
        return _guard.pre(tool_name, args or {}, cwd or str(root),
                          session_id, task_id)

    def on_pre_llm(session_id=None, user_message=None, is_first_turn=False, **kw):
        return {"context": build_context(root, _guard, user_message)}

    def on_session_start(session_id=None, **kw):
        return {"context": build_context(root, _guard, None)}

    ctx.register_hook("pre_tool_call", on_pre_tool)
    ctx.register_hook("pre_llm_call", on_pre_llm)
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_system_prompt_section("woof.rules", RULES,
                                       position="after_memory", max_chars=4000)
```

Текст из §8 положить в `<REPO>/.hermes/plugins/woof-guard/data/section-a.txt`
(плагины могут возить data-файлы рядом с собой).

### 9.3 `build_context` — шаблон per-turn инъекции

```
СОСТОЯНИЕ (данные хука, не память модели)

ЗАКРЫТО: <пункты из ROADMAP/PROGRESS, помеченные как закрытые>
ОТКРЫТЫЙ ПУНКТ: <текущий пункт и его стоп-условие>
ИЗМЕНЕНО В РЕПО: <git status --porcelain, не более 15 строк>
IMPACT-НАБОР: <команды под эти изменения>
ПОВТОРЫ ЗА ПОСЛЕДНИЕ 20 ВЫЗОВОВ: <сигнатура xN, или «нет»>
ПОСЛЕДНЯЯ ПРИЁМКА: <дата, пункт, таблица>
БЛОКИРОВКИ ХУКА: <последний block и причина, или «нет»>

Если «ПОВТОРЫ» не пустой — сначала смени стратегию, потом вызывай инструмент.
Если «ОТКРЫТЫЙ ПУНКТ» уже есть в «ЗАКРЫТО» — остановись и спроси владельца.
```

Инъекция не должна попадать в сохраняемый транскрипт. Эскалация: на 2-м
идентичном шаге — строка, на 3-м — блок действия. Предупреждение текстом само
по себе моделью игнорируется, поэтому всегда сопровождается действием.

### 9.4 `win/guard.cmd` (образец обёртки)

```bat
@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"<абсолютный путь к python.exe из П0>" "%~dp0..\guard.py"
```

Ничего не печатать кроме вывода Python. `%~dp0` даёт каталог обёртки с
обратным слэшем на конце — это нормально для аргумента командной строки, но в
`config.yaml` путь к самой обёртке писать прямыми слэшами.

## 10. ФОРМАТ ОТЧЁТА ПО КАЖДОМУ ПУНКТУ

| LAYER | EXPECTED | ACTUAL | STATUS |
|---|---|---|---|

STATUS: `PASS` / `FAIL` / `NOT RUN` (+ причина). Строка на каждую проверку.
Отдельно — список созданных и изменённых файлов. Отдельно — что нужно от
владельца.

## 11. ЧЕГО НЕ ДЕЛАТЬ

- Не писать свой AST-сканер, граф импортов, анализатор зависимостей.
- Не патчить ядро hermes (`D:/.hermes/hermes-agent/**`).
- Не включать `hooks_auto_accept: true`, не ставить MCP с `trust: full`.
- Не добавлять зависимости без разрешения владельца.
- Не коммитить и не пушить без команды.
- Не перезапускать hermes/браузер/игру «чтобы применились правки».
- Не убивать процессы по имени образа (`taskkill /IM python.exe` и подобное).
- Не писать обратные слэши в `config.yaml`, не использовать `&&`, `|`, `%VAR%`
  в `command:` хуков.
- Не объявлять успех без вывода инструмента.

## 12. ПРОВЕРКА ПОСЛЕ УСТАНОВКИ

```
hermes plugins list
hermes plugins enable woof-guard
hermes hooks list
hermes hooks test pre_tool_call --for-tool terminal
hermes hooks test pre_llm_call
hermes tools
```

Помнить про баг #115968: при ошибке или таймауте `hooks test` не показывает
решение — проверять прямым вызовом хука с синтетическим JSON на stdin.

Атрибуция: производный артефакт проекта MaleCNS, CC BY 4.0.
