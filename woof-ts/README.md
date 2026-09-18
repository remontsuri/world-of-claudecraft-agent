# woof-ts — автономный агент World of Claudecraft (лёгкий стек)

Активная линия репозитория. Агент сам играет в мир игры `levy-street/world-of-claudecraft`
(MIT, read-only для нас) и сам подбирает себе пороги решений. Стек: Node 20, TypeScript,
esbuild, vitest. Веб-фреймворков нет и не будет: приёмка — CLI-прогон и evidence-файл.

## Документы линии

| Файл | О чём |
|---|---|
| `BRIDGE.md` | шов `World`, транспорты, NDJSON-контракт, что видно и чего не видно по проводу, синхронный канал, найденные разрывы политики |
| `LEARNING.md` | контур самоулучшения: целевая функция, сетка порогов, сплит сидов, история, правила |
| `ONLINE-WORLD.md` | переход к живому миру: авторитетный сервер `:8787`, `/ws`, словарь возможностей из `src/world_api.ts` |
| `PROGRESS-2026-09-18.md` | что сделано и чем доказано (датированные секции, не переписываются) |
| `ROADMAP.md` | долг линии: что открыто и в каком порядке |
| `../AGENTS.md` | стоячие правила репозитория (git, процессы, границы, проверки) |
| `../knowledge/woof-ts.md` | датированные факты и решения линии |

## Команды

```bash
bash tools/setup_game.sh        # клон игры (sparse, blobless) + зависимости + сборка
bash tools/build_env.sh         # env-сервер игры нашим esbuild -> dist-env/env_server.cjs
bash tools/check_all.sh         # ВСЕ проверки (их же зовёт пре-коммит хук)
npm test                        # vitest: 62 теста в 6 файлах, 15 из них на живом env-сервере игры
npm run typecheck               # tsc --noEmit

node dist/run.mjs --seed 42 --steps 150 --quiet                        # стенд (in-process Sim)
node dist/run.mjs --transport ndjson --seed 42 --steps 120 --quiet     # бридж (мир в процессе игры)
node dist/run.mjs --seed 42 --steps 400 --every                        # трассировка каждого решения
node dist/tune.mjs --steps 150 --train-seeds 42,43 --val-seeds 44      # подбор порогов
WOOF_PARAMS=learning/best.json node dist/run.mjs --seed 42 --steps 150 # прогон с найденным набором
```

### Windows 11

Окружение чинится и проверяется одной командой (причина и лечение — в
`../knowledge/pitfalls.md`, запись «дерево игры и резолвер расширений»):

```bat
cd /d D:\<путь-к-репо>\woof-ts
tools\fix_windows_env.bat
:: дерево игры в другом месте / очистить его на месте:
tools\fix_windows_env.bat -GameDir D:\woc-game -CleanInPlace
```

Сценарий идемпотентен и делает по шагам: удаляет копию дерева игры `.game-cjs\`
(копия запрещена — факты берутся импортом из upstream); проверяет дерево игры на
собранный вывод (`.js/.cjs/.mjs` в `src\sim` и `headless`); если дерево загрязнено —
по умолчанию **не трогает его**, а кладёт чистый sparse-клон рядом (`D:\woc-game-clean`)
и переводит ссылку на него (`-CleanInPlace` разрешает `git clean -xd src headless`
на месте); создаёт `game` как **junction** (`mklink /J`, права разработчика не нужны);
добавляет в `vitest.config.ts` блок `resolve.extensions` с `.ts` раньше `.js`; ставит
зависимости, собирает, сверяет факты и гоняет тесты. В конце — таблица `Шаг | Статус |
Детали` и код возврата: 0 = окружение готово.

Ожидаемые числа: `сверка фактов: OK`, `Test Files 6 passed (6)`, `Tests 62 passed (62)`.
Полный гейт линии — `bash tools/check_all.sh` в Git Bash.

Флаги `run.mjs`: `--seed`, `--class`, `--steps` (бюджет решений агента), `--transport
sim|ndjson`, `--env-server`, `--npc-view` (только стенд; `0` — привилегия, помечается в
evidence), `--every`, `--quiet`, `--json <путь>`. Код возврата 1 = «не было убийств» или
«мир упал» — поэтому результат читаем по `SUMMARY` и evidence, а не по коду.

## Устройство

```
src/
  facts.ts              факты игры ИМПОРТОМ из дерева игры (obs 607, actions 61, 224 квеста,
                        размеры мира, лагеря, NPC, abilitiesKnownAt) — руками ничего не переписано
  world/
    world.ts            интерфейс World + capabilities (единственный шов к миру)
    types.ts            типы наблюдения, действий, счётчиков
    sim_world.ts        транспорт in-process: src/sim игры в нашем процессе
    quest_policy.ts     предсказание выдачи квеста из контент-данных (сверяется с игрой в тестах)
  bridge/
    obs.ts              раскладка obs, выведенная из фактов (падает, если upstream сместил баланс)
    env_client.ts       NDJSON-клиент: info/reset/step/close, ошибки -> исключение + хвост stderr
    sync_channel.ts     синхронный канал: воркер + SharedArrayBuffer + Atomics
    ndjson_bridge.ts    World поверх env-сервера: что не видно по проводу — объявлено, не подделано
  memory/memory.ts      пятна мобов, квестодатели, посещённые клетки, провалы навыков
  decision/fsm.ts       фаза квеста ВЫВОДИТСЯ из наблюдения (syncFrom)
  decision/arbitration.ts  владелец решения: survival gate -> PHASE_ALLOWED -> фильтр мира -> антицикл
  skills/canon.ts       канон навыков (один источник истины об индексах действий)
  skills/executor.ts    исполнение навыков + композиты (navigate/explore/flee/return_to_giver/noop)
  policy/params.ts      таблица порогов PARAM_SPECS (34): def, min, max, шаг, группа, пояснение
  learn/objective.ts    целевая функция + сплит сидов (объявлены до измерения)
  learn/tune.ts         покоординатный подбор отдельными процессами, история, отчёт
  core/agent.ts         контур OBSERVE -> DECIDE -> EXECUTE -> VERIFY -> LEARN
  core/build.ts         сборка агента поверх любого World
  run.ts                CLI, печать возможностей и диффа порогов до прогона, evidence
tools/                  setup_game.sh, build_env.sh, check_all.sh, verify_facts.ts, probe/diag-*
tests/                  facts, quest_policy, world_seam, params, determinism, bridge_env (живой мир)
learning/               history.jsonl (append-only), best.json, last_report.md
evidence/<дата>/        доказательства прогонов (отслеживаются); evidence/tuning/ — черновики (нет)
```

## Приёмка

Пороги объявлены до замера (см. `../README.md` и `../knowledge/verification.md` §4b):

| Мир | Бюджет | world_steps | kills | deaths | quests_done | first_turn_in |
|---|---|---|---|---|---|---|
| стенд `sim`, seed 42, warrior | 150 решений | 4323 | 24 | 22 | 2 | шаг 12 |
| стенд `sim`, seed 42, warrior | 400 решений | 6696 | 31 | 26 | 2 | шаг 12 |
| бридж `ndjson`, seed 42, warrior | 120 решений | 5530 | 2 | 0 | 1 | шаг 6 |

`check_all.sh` обязан печатать `ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ`. Любое изменение эталона — находка:
причина пишется в `PROGRESS-<дата>.md` и `../knowledge/woof-ts.md`, а не молча правится в таблице.
