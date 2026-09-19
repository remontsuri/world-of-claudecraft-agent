# woof-ts и мир, сопоставимый с онлайн-игрой

Зачем этот файл: целевой мир агента — не тепличный детерминированный стенд, а мир
уровня онлайн-игры (реальное время, задержки, другие игроки, права на лут, никакой
возможности читать внутренности симуляции). Поэтому in-process `Sim` у нас —
**один из адаптеров**, а не основа архитектуры.

## Игра уже устроена так же (факт, а не наше допущение)

`src/world_api.ts` дерева игры, дословно:

> «The surface the renderer + HUD need from a game world. The offline `Sim`
> satisfies this structurally; the online `ClientWorld` implements it by
> mirroring server snapshots and sending commands over the socket.»

То есть у игры один и тот же интерфейс мира (`IWorld`, собран из фасетов
`src/world_api/*.ts`) реализован дважды: офлайн-симуляцией и онлайн-клиентом.
Наш `src/world/world.ts` (`interface World`) — проекция этого шва на нужды агента.

Фасеты `IWorld` (карта из того же файла): entity_roster, combat, **targeting**,
interaction, **loot (need/greed roll)**, **inventory (bags, equipment, vendor,
copper)**, cosmetics, **quests (quest log + accept/turn-in/abandon)**,
progression_xp, talents, pet, party, trade, chat, duel_arena, battleground,
social_graph, market, mail, dungeons, delves, daily_rewards, telemetry,
professions, bank, guild_bank, mounts, dungeon_finder, deeds, farming, reliquary.

Протокольный словарь — `COMMAND_NAMES` там же: `castSlot`, `castAt`, `cast`,
`cancel_aura`, **`target`**, **`tab`**, `targetNearest`, `tabFriendly`,
`targetNearestFriendly`, `attack`, `stopattack`, `interact`, `loot`,
`harvestCorpse`, `lootRoll`, `pickup`, `accept`, …

И ключевая деталь про стенд (`DISPATCH_ONLY_COMMANDS`):

> «`targetNearest` is called directly on the Sim by the headless RL action layer,
> never over the wire.»

То есть **наш «канонический» выбор цели `target_nearest` — это RL-подстановка**,
а в живом мире есть полноценные `target`/`tab`. Там же `dev_level`,
`dev_teleport`, `dev_give`, `dev_complete_quest`, `dev_complete_all_quests` —
читы под `ALLOW_DEV_COMMANDS`, «never production»: агент их не использует и не
будет, это заявлено.

## Аудит: что у нас сейчас привилегия стенда

| Что использует агент | Стенд (in-process Sim) | Живой мир | Что меняется у агента |
|---|---|---|---|
| Абсолютные координаты сущностей (`EntityView.x/z`) | даёт | снапшоты сервера дают позиции в пределах видимости клиента, не глобально | навигация обязана работать на относительных дистанция/пеленг + счисление пути; координатные цели — только когда `absoluteCoords=true` |
| Состояние любого квеста (`questState`) | даёт | `IWorldQuests`: журнал + accept/turn-in/abandon | предсказание «какой квест выдаст NPC» (`predictedAccept`) опирается на контент-данные; на живом мире его надо подтверждать эмпирически (пин-тест уже в плане) |
| Число предметов (`Sim.countItem`) | даёт | `IWorldInventory`: bags — даёт | остается, но через `capabilities.itemCountApi`; без неё лут честно `LOOT_UNVERIFIED`, а не «не удалось» |
| Счётчики kills/deaths/questsCompleted | мгновенно, дельта на шаг | `IWorldDeeds`/progression: снапшоты с задержкой | метрики считать по событиям, а не по дельте счётчика за одно решение |
| Детерминизм/replay по seed | есть | нет | тесты детерминизма — только стендовые; acceptance живого мира = серия прогонов и медиана, не один прогон |
| Темп: frameSkip=5 (0.25 с мира на решение) | пакет тиков | реальное время + задержка связи | нужен бюджет решения в мс, pacing команд, таймауты и повторная сверка состояния |
| Другие игроки | нет | есть | конкуренция за мобов и лут (`corpseLootRights`, `lootHasGoneFfa` в `interaction.ts`), need/greed roll, кража агgro, PvP → метрики шумят, нужен медианный отчёт |
| Выбор цели | только `target_nearest` | `target`, `tab` | `farm` сможет бить именно цель квеста: ветка уже развилена по `capabilities.targetSelection` |
| Отказ от квеста | нет | `abandon` | зависший непроходимый квест лечится отказом; сейчас — только политика «не брать» + `exhaustedGivers` |
| Продавец | нет (профессии/торговля CUT upstream) | `IWorldInventory`: vendor | полные сумки (гипотеза за `LOOT_FAILED`) лечатся продажей; `sell_junk` станет поддерживаемым навыком |
| Груп-лут | нет | need/greed roll | нужна политика роллов, иначе лут теряется |
| Читы `dev_*` | сервер их диспетчит | env-gated, never production | не используем никогда — заявлено |

## Что уже переведено на онлайн-совместимую модель наблюдения

Раньше NPC были видны агенту на всю карту (`--npc-view 0` по умолчанию) — это
привилегия стенда: живой клиент получает сущности только в радиусе интереса
(`PLAYER_INTEREST_DROP_RADIUS = 100`, src/sim/types.ts:56; headless env держит
собственный throttle 80, headless/env_server.ts:120). Теперь:

- **Живые сущности** (мобы, трупы, объекты и NPC alike) видны в `VIEW_RADIUS = 60`
  ярдов — совпадает с RL-наблюдением игры (`obs.ts: d < 60`) и строже радиуса
  интереса. Флаг `--npc-view 0` оставлен только для диагностики и печатает
  предупреждение «ПРИВИЛЕГИЯ СТЕНДА», а в evidence пишется
  `observationPolicy.note` о непереносимости такого результата.
- **Знание карты** — отдельный слой `WorldModel.mapPins`, собранный из
  статического контента игры (`NPCS[*].pos` + `questIds`): где стоит квестодатель
  и кто принимает наш квест. Это ровно то, что клиент знает из карты и журнала
  квестов (аналог меток «!» на карте), а не чтение состояния мира. Доступность
  квеста на пине определяется через `questState` (объявлено как
  `questStateApi`); если живой мир её не даст, агент обязан дойти и спросить —
  это объявленная деградация, а не молчаливая подмена.
- Лагеря мобов (`CAMPS`) и точки интереса зоны (`pois`: Eastbrook, Wolf Run,
  Boar Meadow, Mirror Lake, Sableweb, Copper Dig, Bandit Camp, …) — тот же слой
  клиентского знания карты.

### Результат: честная модель оказалась не хуже, а лучше

seed 42, warrior, 150 решений:

| модель наблюдения | world_steps | kills | deaths | quests_done | первая сдача |
|---|---|---|---|---|---|
| привилегия стенда (`--npc-view 0`) | 3891 | 24 | 13 | 1 | шаг 91 |
| онлайн-совместимая (NPC=60 + слой карты) | 4323 | 24 | 22 | **2** | **шаг 12** |

Цепочка честного прогона: `ACCEPT:q_hub_know_your_numbers` → 10 ударов по
манекену → `TURN_IN` (шаг 11) → поход к Marshal Redbrook **по пину карты** →
`ACCEPT:q_wolves` → 8 убийств forest_wolf → `TURN_IN` (шаг 74) →
`ACCEPT:q_greyjaw`. В журнале видно, что живых NPC агент теперь видит столько,
сколько показывает мир: `npcs=1`, `npcs=2`, `npcs=18` — вместо прежних `npcs=124`.

Детерминизм при этом сохранён: два прогона seed 42/150 дают идентичный SUMMARY.

### Что онлайн-масштаб уже показал (открыто)

- **seed 7 — хрупкость**: kills=1, deaths=183, quests_done=1. Причина видна в
  журнале: на пути к целям агент проходит сквозь лагеря (прямой подход), на него
  сваливается стая, а убежать пешком нельзя (мобы быстрее игрока), плюс у
  Drillmaster Hale после hub-квеста рядом остаются пауки, и арбитраж выбирает
  `farm` раньше `navigate` (ближний бой приоритетнее похода) — агент ввязывается
  в бой у города вместо похода к квестодателю.
  Лечение (по фактам игры, а не по догадке): (1) маршрут в обход лагерей —
  `CAMPS` дают центры и радиусы, `pois`/`hub` дают безопасные точки; (2) боевая
  политика способностей (AoE/защита/самохил) вместо «первой готовой»; (3) правило
  «есть пин квестодателя и нет активного квеста → поход важнее случайного боя».
  В живом мире сид выбрать нельзя, поэтому robustness по сидам — часть
  acceptance, а не частность стенда.
- `tsc --noEmit`: по нашим файлам 0 ошибок; 66 ошибок приходят из неполного клона
  игры (нет каталога `src/world_api/`, на который ссылается `src/sim`). Это ещё
  один довод дотянуть клон: без него фасеты `IWorld` читаются только по
  баррел-файлу.

## Объявление возможностей (печатается до прогона, пишется в evidence)

`WorldCapabilities` в `src/world/world.ts`, значения стенда — в
`sim_world.ts: get capabilities()`:

```
[WoOF] мир: транспорт=in-process, frameSkip=5, реальное время=нет, другие игроки=нет, задержка=0 мс
[WoOF] мир: абсолютные координаты=да, состояние любого квеста=да, предметы в сумках=да, данные контента=да, детерминизм=да
[WoOF] мир: выбор цели=nearest-only, сдача/отказ от квеста=только то, что даёт стенд, продавец=нет, груп-лут (roll)=нет, словарь команд=rl-actions
```

Правило: ничего молчаливого. Если мир не даёт возможность, зависящий код либо не
вызывается, либо сообщает «не проверено» (`LOOT_UNVERIFIED`), либо бросает
исключение (`countItem` при `itemCountApi=false`).

## Адаптеры мира (план)

1. **`sim_world.ts`** — готов: in-process `Sim`, детерминирован, `rl-actions`,
   `nearest-only`. Стенд для отладки политик и тестов.
2. **`net_world.ts`** — NDJSON-клиент к headless env server (`headless/env_server.ts`):
   `info`/`reset`/`step`, `obs = number[]` длины `obsSize()`, `action = int` в
   `ACTIONS`, ошибки приходят как `{error:"..."}`, frameSkip 5, maxSteps 8000,
   respawnSeconds 15. Тот же набор возможностей, что у стенда, но уже через
   процессную границу: проверка, что агент не привязан к in-process-доступу.
3. **`live_world.ts`** — клиент авторитетного сервера (`npm run server`, :8787,
   `/ws`; `npm run dev` проксирует `/api`, `/admin/api`, `/ws` на :8787).
   Возможности богаче стенда: `target`/`tab`, `abandon`, vendor, loot roll,
   party/trade/market/mail, реальное время, другие игроки. Опора — снапшоты
   `selfWireJson`/`applySnapshot` (пин-тест игры `tests/snapshots.test.ts`, W0a)
   и словарь `COMMAND_NAMES` (W0b), паритет `IWorld` между `Sim` и `ClientWorld`
   (W0c).

Что для этого нужно дотянуть в рабочее дерево игры: сейчас клон разреженный
(`headless/`, `python/`, `src/sim/`) и без `.git`, поэтому `src/world_api/`,
`server/` и клиентский `ClientWorld` надо взять отдельным клоном с нужными путями
— иначе адаптер живого мира придётся писать по догадке, а это прямо против
правила «факты — из дерева игры».

## Что уже сделано, чтобы порт не был стендово-зависимым

- `interface World` + `WorldCapabilities`; `SimWorld implements World`; агент,
  исполнитель и арбитраж типизированы интерфейсом, а не конкретным стендом.
- Выбор цели развилён по `targetSelection` (nearest-only → `target_nearest`,
  free → `world.targetEntity(id)`).
- Лут без `itemCountApi` даёт `LOOT_UNVERIFIED` (честно), а не ложный провал.
- Инвариант «любое решение двигает мир» (`frozen_guards` в SUMMARY) — в живом
  мире это же свойство спасает от рассинхрона с сервером.
- Все игровые факты (obs/actions/диапазоны/классы/квесты/таблицы лута/лагеря)
  импортируются из дерева игры, руками не переписаны: замена стенда на живой мир
  не требует переписывания фактов.

## Перенос acceptance-критериев на живой мир

- Детерминизм и «два прогона одного сида identical» — остаются стендовыми
  тестами; для живого мира критерий заменяется на **серию из N прогонов и
  медиану** kills/quests_done/deaths с объявленным N до измерения.
- Пороги (HP, толпа, уровень моба, дистанции) объявляются до измерения в любом
  мире; на живом мире к ним добавляется бюджет решения в мс и допустимая доля
  потерянных/повторённых команд.
- Метрика `deaths` на живом мире включает чужое вмешательство (PvP, кража агgro),
  поэтому сравнивать её со стендовой напрямую нельзя — только внутри одного мира.

---

## 2026-09-18 — факты из серверной части игры (полный клон v0.43.2, GAME_FULL=1)

Записано по свежему клону `GAME_DIR=… GAME_FULL=1 bash tools/setup_game.sh` (пин v0.43.2).
Клон удалён после снятия фактов: полное дерево занимает **4.0 ГБ** (docs, медиа, tests),
а предел снимка рабочего места ~128 МБ — держать его в песочнице нельзя. Клонируем
на время работы и удаляем, либо держим вне workspace.

**Полное дерево совместимо с нашей линией**: `tsc --noEmit` чисто и `сверка фактов: OK`
(obs=607, actions=61, 224 квеста, цели kill=106 collect=76 interact=60 gather=4 escort=4
farm=2) — то есть `GAME_FULL=1` не ломает гейт, факты те же, что в лёгком дереве.

### Как поднимается живой мир (README игры, «Host your own world (one command)»)

```bash
cp .env.example .env            # задать длинный случайный POSTGRES_PASSWORD
docker compose up -d --build    # postgres и игровой сервер, полностью собранные
# открыть http://localhost:8787 — аккаунты, персонажи и весь мир
```

`docker-compose.yml`: сервисы `postgres` (image `postgres:16-alpine`,
`POSTGRES_USER/DB=eastbrook`, порт `127.0.0.1:5433:5432`, volume `eastbrook_pgdata`),
`game` (image `eastbrook-game:${EASTBROOK_IMAGE_TAG:-local}`, `DATABASE_URL=postgres://…@postgres:5432/eastbrook`,
порт `127.0.0.1:8787:8787`, монтируются media-cache/sfx-runtime/parse-spool,
`host.docker.internal:host-gateway`) и опциональный `discord-bot`.
Порты привязаны к `127.0.0.1` — мир локальный, наружу не торчит.

Сервер: `npm run server` = `npm run build:server && node dist-server/server.cjs`;
персист в Postgres, раздаёт собранный клиент из `dist/` (`server/CLAUDE.md`).
`main.ts` — HTTP + prefix-ladder (`/api`, `/admin/api`, `/oauth`, `/internal`) и
upgrade WS на `/ws` (собирает deps-мешок `createWsAuth`). `game.ts` — `GameServer`:
владеет `Sim`, цикл 50 мс, interest-scoped снапшоты, диспетчер команд, чат.

Отдельно есть **офлайн-режим в браузере**: `npm run dev` (vite :5173), одиночный мир
без аккаунта и без авторитета сервера, только в dev-сборках (появляется в переключателе
режимов). Именно к нему подключалась замороженная Java-линия через CDP 9222.

### Контракт подключения агента (WS)

Первый кадр рукопожатия — `src/net/world_auth_message.ts`, `buildWebSocketAuthMessage(token, characterId, clientSeed='')`:

```ts
{ t: ONLINE_WORLD_AUTH_TYPE, token, character: <characterId>, clientSeed,
  dungeonEntryFacingWire, timerWire, petSpecialWire, movementWire: 2 }
```

`server/ws_auth.ts` сверяет **каждую** объявленную возможность по точному равенству и
при отсутствии поля молча понижает сессию на legacy-wire — значит все поля обязаны
заполняться из констант игры, а не придумываться (комментарий в самом файле: «an omitted
field silently downgrades the session with nothing reddening»). Строгая проверка
`msg?.t !== ONLINE_WORLD_AUTH_TYPE` идёт до любой работы с учетными данными и БД
(`ws_auth.ts:271`); лимит на IP, лимит допуска на.realm (`MAX_PLAYERS_PER_REALM`,
по умолчанию 5000), аренда персонажа, `game.join`.

Команды клиента уходят одним сокетом кадром `{ t: 'cmd', …payload }`
(`src/net/online.ts:2224`). Любой отказ приходит кадром `{t:'error'}` **до** закрытия
сокета: клиент классифицирует литерал отказа (литералы `ws_auth.ts` — wire-контракт,
совпадают дословно с `src/ui/api_error_i18n.ts`), а отказ без кадра превращается в
тихий цикл ретраев.

**Один персонаж = один сеанс.** `server/linkdead.ts`, `planJoin`: если персонаж уже в
мире — `resume` только для linkdead-сессии, иначе `reject` с литералом
`'character already in world'`; явный takeover — единственный способ занять персонажа
заново (`POST /api/characters/{id}/takeover`, `src/net/online.ts:807`).
**Следствие для нас: человек в браузере и агент не могут одновременно играть одним
персонажем.** Либо у агента свой персонаж (и человек видит его в мире как другого
игрока), либо takeover, который выбрасывает сеанс человека.

### Клиент игры как готовый транспорт

`src/net/online.ts` = REST `Api` (auth, characters, realms, leaderboard, wallet linking)
+ `ClientWorld implements IWorld`: зеркалит авторитетные снапшоты сервера и отправляет
команды по одному WebSocket; **PRESENTATION ONLY** — исходы (бой, лут, зачёт квестов,
таланты) не вычисляет, только отражает состояние сервера (`src/net/CLAUDE.md`).
Локально он вызывает `abilitiesKnownAt`/`computeQuestState` исключительно для отображения
того, что сервер уже решил.

Важная для нас деталь: WebSocket берётся из **global** — тестовый harness подменяет
`globals.WebSocket` своим классом (`tests/helpers/online_harness.ts`, строки ~360–377),
и `ClientWorld` поднимается против заглушки. Значит клиента можно поднять в Node,
подставив global WebSocket (Node 22+: встроенный; Node 20: shim). REST — обычный `fetch`
(в Node 20 есть). Это путь «импортировать upstream, а не переписывать протокол руками»:
наш `WsWorld` становится адаптером `ClientWorld` (IWorld) → наш интерфейс `World`.

### Ограничения сервера, которые обязан уважать агент

* `msg_rate_limit.ts` — pre-parse гейт (бакеты кадров и байт + общее окно злоупотреблений,
  которое кикает), `msg_lanes.ts` — post-parse полосы по классам сообщений;
* `ws_backpressure.ts` — сервер завершает сессию, у которой `ws.bufferedAmount` превысил
  жёсткий лимит (не читающий клиент может уронить realm по памяти);
* `keepalive_sweep.ts` — keepalive-sweep с защитой от late-fire и жёсткий дедлайн тишины
  `WS_SILENCE_DEADLINE_MS` (10 минут без кадров → reap);
* `bot_detector/contract.ts` + `stub.ts` — seam антибота: no-op заглушка, когда приватный
  клон отсутствует (локально, значит, скорее всего no-op), плюс `antibot_config_db.ts`
  (JSONB-конфиг на realm + append-only аудит).

Для агента это означает: команды отправлять в темпе живого клиента (не очередью из
сотен кадров), читать всё, что присылает сервер, держать keepalive. Это объявляется в
возможностях транспорта (задержка, реальное время, рейт-окна) и проверяется в приёмке:
кик по рейт-лимиту — провал, а не «сервер строгий».

`ALLOW_DEV_COMMANDS=1` включает весь набор `/dev`-читов: level и teleport
(«the level and teleport cheats the test bots use»), выдачу предметов, спавн мобов,
телепорты в инстанции и внутриигровой dev-GUI. Только локально; в проде — никогда
(README игры). Для наших прогонов это привилегия: если она включена, evidence обязан
это объявлять, а результат не считается переносимым.

### План A1 (живой мир) — шаги и критерии

| Шаг | Что | Критерий |
|---|---|---|
| A1.1 | Поднять мир: `GAME_FULL=1` клон, `.env`, `docker compose up -d --build`, health-проверка :8787; инструмент `tools/run_world.sh` | `curl -sf http://127.0.0.1:8787/…/health` отвечает; в браузере мир открывается |
| A1.2 | Аккаунт и персонаж агента через REST (`Api` из `src/net/online.ts` или минимальные fetch-вызовы): регистрация/логин → token, список/создание персонажа → id | токен и characterId получены; секреты только из env и никогда в evidence |
| A1.3 | `src/bridge/ws_world.ts` + `ws_client.ts`: `ClientWorld` (импорт из игры) против global WebSocket, адаптация IWorld → наш `World`; возможности объявлены (стабильные id, серверное состояние квестов, realtime, otherPlayers, targetSelection='free') | `--transport ws` поднимает сессию и получает снапшот; возможности печатаются до прогона |
| A1.4 | Команды: маппинг наших навыков на `{t:'cmd', …}`; темп в пределах рейт-окон; keepalive; reconnect/backoff (импорт чистых модулей игры `src/net/backoff.ts`, `reconnect_policy.ts`) | 1000 команд без кика; обрыв соединения → переподключение без потери эпизода |
| A1.5 | Приёмка: тот же агент **без правок политики** делает ≥1 убийство и ≥1 квест за живым сервером; человек видит агента в браузере как другого игрока | `[Agent] SUMMARY … kills≥1 quests_done≥1` при `--transport ws`; evidence с объявленными возможностями |
| A1.6 | Записи: `PROGRESS-<дата>.md`, `knowledge/woof-ts.md`, обновление эталонов (живой мир — другие единицы: реальное время, снапшоты 50 мс) | датированные строки, эталоны объявлены до замера |

### Развилка, которую решает владелец

* **A (рекомендую): агент — отдельный WS-клиент со своим персонажем.** Человек держит
  браузер на :8787 и видит агента в мире. Никакого CDP, никакой зависимости от вкладки.
  Ограничение сервера (один сеанс на персонажа) при этом не мешает.
* **B: агент играет персонажем человека.** Упирается в `'character already in world'`:
  takeover выбросит сеанс браузера, то есть «смотреть, как агент играет моим героем»
  не получится — смотреть будет нечем.
* **C: офлайн-режим в браузере (`npm run dev`, :5173) + CDP 9222** — путь замороженной
  Java-линии: сервер и Postgres не нужны, но клиент presentation-only, стабильного API
  нет, правила репозитория запрещают перезагружать страницу и трогать игру, в которой
  уже играет пользователь; наблюдение — только чтением `window.__game.sim`.

### Открытый технический вопрос (объявить до реализации)

WebSocket-клиент в Node: либо **Node 22+** (глобальный `WebSocket`, ноль зависимостей),
либо одна рантайм-зависимость **`ws@^8`** (та же библиотека, которую использует сама
игра). Сейчас линия объявляет Node 20+ и ноль рантайм-зависимостей — решение и его
причина обязаны попасть в `AGENTS.md` §«Стек активной линии» и `knowledge/woof-ts.md`
до первой строчки кода A1.3.


---

## 2026-09-18 (вечер) — что уже реализовано и что дальше

Реализовано (A1.0/A1.1, статусы в `ROADMAP.md`):

* `src/bridge/ws_protocol.ts` — кадр рукопожатия (`buildAuthFrame`), кадр команды
  (`buildCommandFrame`), `assertClientCommand` (dispatch-only = ПРОВАЛ), `parseFrame`
  (не-JSON и кадр без `t` = ПРОВАЛ), `liveWorldCapabilities` + `unmeasuredCapabilityNotes`.
  Все константы — импорт из `game/src/world_api.ts`, который есть и в лёгком дереве фактов.
* `src/bridge/ws_socket.ts` — `SocketLike`, `adaptSocket` (browser-style и `ws`),
  `resolveSocketFactory` (injected → global → ws → ПРОВАЛ), `NO_SOCKET_MESSAGE`.
* `tests/ws_live.test.ts` — 21 проверка; привязка `movementWire` к исходнику upstream
  пропускается вслух, если дерево лёгкое.
* `tools/run_world.sh` — подъём мира (см. PROGRESS: проверено с заглушкой docker).

REST-пути, снятые с `server/*.ts` v0.43.2 (для A1.2): `/api/register`, `/api/login`,
`/api/me/characters`, `/api/characters`, `/api/characters/:id`, `/api/characters/:id/sheet`,
`/api/characters/:id/takeover`, `/api/realms`, `/api/status`, `/api/account`.
Тела запросов и порядок шагов берутся из `src/net/online.ts` (`Api`) на машине с полным
чекаутом — угадывать форму полей нельзя.

Словарь команд v0.43.2 (`COMMAND_NAMES`, `src/world_api.ts:453`), нужный агенту в первую
очередь: `cast`, `target`, `tab`, `attack`, `stopattack`, `interact`, `loot`, `pickup`,
`accept`, `turnin`, `abandon`, `equip`, `inv_move`, `unequip_item`, `use`, `discard`,
`buy`, `sell`, `buyback`, `sell_all_junk`, `harvest_node`, `craft_item`, `chat`, `emote`,
`pinvite`/`paccept`/`pdecline`/`pleave`. Dispatch-only (не отправляем): `dev_level`,
`dev_teleport`, `dev_give`, `dev_complete_quest`, `dev_complete_all_quests`,
`enter_crypt`, `leave_crypt`, `social_refresh`, `targetNearest`, `dev_bg_start`,
`mount_train_answer`, `mount_train_abort`, `dev_profiler_invulnerable`, `rift_enchant_item`.

Дальше по шагам A1.2 → A1.6 (критерии в `ROADMAP.md`).
