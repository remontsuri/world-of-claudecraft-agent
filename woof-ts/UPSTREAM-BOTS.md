# Боты и агенты World of ClaudeCraft: что уже существует (обзор 2026-09-18)

Запрос владельца: «нужен агент, который сам играет в World of ClaudeCraft; поищи в
интернете, может кто-то делал бота». Ниже — что нашлось, с источниками, и что из этого
мы берём. Правило линии соблюдено: факты сняты с дерева игры v0.43.2 и с публичных
страниц, а не по памяти.

## 1. Сторонние агенты: не найдено

Поиск по `"world of claudecraft" bot/agent/RL/PPO/stable-baselines3/WoWClassicEnv`
выдал только **форки самого игрового репозитория** (PoorInfz, demon820308, vagners,
lionfart, AccompliceNZ, lumon-bdip, dandpb, SuinegXY, Botro-Plays, EPOSigma) и общие
материалы по Stable-Baselines3/HuggingFace, к игре не относящиеся. Ни обученной модели,
ни самостоятельного бота третьей стороны не нашлось.

Единственный известный сторонний агентский проект — `remontsuri/world-of-claudecraft-agent`
(Java + Chrome DevTools Protocol, мост :8791, MCP :8792): он уже отревьюирован этим
репозиторием и лежит в `archive/` (выводы не переписываются; линия заморожена).

## 2. Боты есть в самой игре — и они играют по-настоящему

`scripts/` upstream v0.43.2 (список снят с дерева игры):

| Скрипт | Что делает | Транспорт |
|---|---|---|
| `crypt_raid.mjs` | **пять ботов** (warrior, paladin, priest, mage, hunter) с рейдовым ИИ (focus fire + два хилера) собираются в группу, входят в Hollow Crypt и доходят до Morthen the Gravecaller; README: «clears the Hollow Crypt in about five minutes» | провод (WS к серверу) |
| `mp_integration.mjs` | register, login, character CRUD, два клиента в одном мире видят друг друга, синхронизация движения, бой, чат, персистентность через переподключение | REST + WS |
| `social_e2e.mjs` | торговля и дуэль по проводу | REST + WS |
| `arena_visual.mjs` | два клиента встают в очередь и дерутся ranked 1v1 | REST + WS + браузер |
| `squad_visual.mjs` | несколько клиентов играют Thornhollow Fields 5v5 CTF | REST + WS + браузер |
| `smoke_browser.mjs`, `smoke_mage.mjs`, `smoke_rogue.mjs`, `visual_tour.mjs`, `tour_temple.mjs`, `perf_tour.mjs` | end-to-end и скриншот-туры: воин, маг (каст, полиморф, conjure/drink, смерть и release), разбойник | браузер через `puppeteer-core`, нужен `npm run dev` |
| `lib/world_auth.mjs` | кадр рукопожатия и литерал несовместимости версий для Node-клиентов | — |

Разделение upstream формулирует сам (README/docs, раздел Development): «The screenshot and
smoke scripts drive real browsers via puppeteer-core and need `npm run dev` running; the
wire-level scripts (`mp_integration.mjs`, `social_e2e.mjs`, `crypt_raid.mjs`) talk to the
server directly and need `npm run server` instead».

**Вывод для нас:** играющие боты upstream — проводные (WS к авторитетному серверу),
а браузер они используют для скриншотов и UI-smoke, не для игры агента. То есть выбранная
нами схема A (агент — отдельный WS-клиент, человек смотрит в браузере) совпадает со
способом, которым ботов делает сам upstream.

## 3. Контракт провода, снятый с рабочих ботов upstream

REST (`mp_integration.mjs`, `BASE = SERVER_URL ?? http://localhost:8787`):
* `POST /api/register` → `{token}`; `POST /api/login` → `{token}`; `/api/status`;
  CRUD персонажей; заголовок `Authorization: Bearer <token>`;
* имена персонажей — только буквы («classic rules»);
* повторная регистрация того же имени и вход с неверным паролем проверяются как отказы.

WS (`WS_BASE = BASE.replace(/^http/, 'ws')`, сокет `${WS_BASE}/ws`, библиотека `ws`):
* первый кадр — `worldAuthMessage(token, characterId)` = `{t:'auth-world-29', token, character}`.
  Upstream держит этот дискриминатор в синхронизации с `src/world_api.ts` отдельным
  vitest-контрактом «freshness»; наш `buildAuthFrame` шлёт ПОЛНЫЙ кадр (со всеми
  wire-версиями из `src/net/world_auth_message.ts`), потому что отсутствующее поле
  сервер молча понижает до legacy-wire;
* исходящие: `{t:'cmd', cmd: <ClientCommand>, ...}` и движение `{t:'input', mi, facing}`
  (`mi` — флаги ввода, компактная форма вида `{f:1, sr:1}`; эквивалент браузерного
  `window.__game.controller.move({forward:true}, facingRadians)`);
* входящие: `t:'hello'` (даёт `pid`), `t:'snap'` (снапшот), `t:'events'` (`list`),
  `t:'error'` (`error`) — отказ всегда кадром, до закрытия сокета.

Модель снапшота (дельта-кодирование — ключевая деталь):
* `self`: тяжёлые поля приходят только при изменении; отсутствующее поле означает
  «как в прошлом снапшоте». Список дельта-полей upstream: `inv, equip, qlog, qdone,
  cds, stats, weapon, party, trade, duel` → их обязан сливать `mergeSelf`;
* сущности: `snap.ents` (записи) + `snap.keep` (id живых, но не изменившихся);
  «полные» записи несут поля личности `k` (kind), `tid` (templateId), `nm` (имя),
  `lv` (уровень), `sc`, `c`, `dgn`, «лёгкие» наследуют их от предыдущего состояния
  → `mergeEnts`; всё, чего нет ни в `ents`, ни в `keep`, — исчезло из интереса;
* поля, которые боты реально читают: `self.x/self.z` (абсолютные координаты),
  `self.hp`, `self.res/self.mres`, `self.rtype` ('mana'), `self.eat/self.drk`,
  `self.dead`, `self.party.members[]` (`m.hp/m.mhp/m.dead`), у сущностей
  `e.k === 'mob'`, `e.dead`, `e.h`, `e.tid === 'morthen'`, `e.hp/e.mhp`.

## 4. Что это меняет в наших возможностях мира

Живой мир по проводу **богаче** headless-наблюдения, и это видно из кода upstream,
а не из наших ожиданий:

| Возможность | headless-бридж (сейчас) | живой мир по проводу |
|---|---|---|
| идентичность сущностей | `slot` (позиция в списке не личность) | `stable` (id в `ents`/`keep`) |
| вид сущности (templateId) | нет | есть (`tid`) |
| абсолютное HP | нет (только доля) | есть (`hp`/`mhp`) |
| абсолютные координаты | нет | есть (`self.x/self.z`) |
| состояние квестов | `observed` (0 неразличим) | серверный журнал (`qlog`/`qdone`) |
| предметы в сумках | нет | есть (`inv`) |
| словарный запас боя | RL-действия | wire-команды + `target`/`tab` (свободная цель) |

Поэтому `liveWorldCapabilities()` объявляет консервативные значения до измерения,
а измерение (A1.6) проводится по этому контракту: `entityIdentity='stable'`,
`entityTemplates=true`, `entityAbsoluteHp=true`, `absoluteCoords=true`,
`itemCountApi=true`, `questStateApi` — по факту `qlog/qdone`.

## 5. Грабли, которые upstream описал сам (и мы закрыли тестом)

* **Чат и каждый `/dev ...`-чит — это КОМАНДА**, а не тип кадра: серверный `case 'chat'`
  sits in the cmd switch (`server/game.ts`), поэтому кадр `{t:'chat'}` верхнего уровня
  не совпадает ни с чем и **молча выбрасывается**, «leaving the script believing its bots
  were levelled, geared or god-moded» (`scripts/lib/world_auth.mjs`). Живой клиент шлёт
  `this.cmd({cmd:'chat', text})`. Наш `buildCommandFrame` ловит `/dev` в тексте чата и
  падает: привилегированный прогон не должен выглядеть обычным.
* `crypt_raid.mjs` работает только при `ALLOW_DEV_COMMANDS=1` и пользуется
  `dev_level`, `dev_teleport`, `dev_give` — это привилегированный сценарий. Наш агент
  dispatch-only токены не отправляет вовсе (проверено тестом), поэтому его прогон
  переносим, а их рейд — нет.
* Литерал несовместимости версий: `ONLINE_WORLD_INCOMPATIBLE_MESSAGE = 'Game and server
  versions are incompatible. Reload or update, then try again.'` — по нему клиент
  отличает смену эпохи раскладки от обычного отказа входа.

## 6. Источники

* Репозиторий игры: https://github.com/levy-street/world-of-claudecraft (v0.43.2, MIT);
  локально — дерево `~/woc-game` (пин версии) и `scripts/`, `src/net/`, `server/` из
  временного клона (в рабочее место не копируются: полный чекаут — гигабайты).
* README игры: разделы «Train an agent (headless RL)», «Host your own world»,
  «Development» (список скриптов и разделение browser/wire), «A tour of the world →
  Dungeons» (пять ботов, ~5 минут, `ALLOW_DEV_COMMANDS=1`).
* Форки (ботов не содержат): PoorInfz, demon820308, vagners, lionfart, AccompliceNZ,
  lumon-bdip, dandpb, SuinegXY, Botro-Plays, EPOSigma.
* Сторонний агентский проект, уже архивированный этим репозиторием:
  `remontsuri/world-of-claudecraft-agent` (см. `archive/`, обзоры не переписываются).

## 7. Что берём в работу

1. Контракт из §3 — как основу `src/bridge/ws_client.ts` (REST-вход, WS-сеанс,
   `hello`/`snap`/`events`/`error`, `mergeSelf`/`mergeEnts`) и `src/world/live_world.ts`
   (`World` поверх провода). Приёмы upstream читаем, но не копируем в наше дерево:
   наши модули пишутся под наш шов мира, а факты сверяются с деревом игры.
2. Возможности из §4 — как план измерения A1.6 (объявляем только то, что увидели в кадре).
3. Запреты из §5 — как тесты (уже есть: dispatch-only, `/dev` в чате).
4. Браузер — для наблюдения за агентом в мире :8787 (схема A). Офлайн-режим
   (`pnpm run dev` → :5173 → «Play Offline») остаётся доступным человеку, но агента
   к нему подключаем только отдельной задачей C1 (CDP, `window.__game.sim` +
   `src/sim/obs.ts`), и такой прогон объявляется привилегированным
   (`devCommands: import.meta.env.DEV`) и недетерминированным (темп задаёт
   `requestAnimationFrame`).

---

## 8. Добавлено 2026-09-18 (второй круг поиска): ClaudeCraft Arena — агент авторов игры

Найдено главное: **агент, который сам играет в World of ClaudeCraft, уже существует и
работает вживую** — его сделали сами авторы/сообщество игры.

### Что это

* **ClaudeCraft Arena** (пост в r/ClaudeAI, 2026): «Мы построили самоулучшающийся
  агентский харнесс (**форк Hermes**) и запустили четыре фронтирные модели — Claude,
  ChatGPT, Grok, Kimi K3 — на одном живом сервере. Каждая — VTuber со своим аватаром,
  личностью и голосом ElevenLabs. Они выполняют квесты, торгуют, сражаются, оскорбляют
  друг друга и **переписывают собственные стратегии в реальном времени**. Живой
  XP-лидерборд определяет, кто действительно сильнее».
  Трансляция: https://www.twitch.tv/claudeplaysclaudecraft
  Тред: https://www.reddit.com/r/ClaudeAI/comments/1vl45c6/claudecraft_arena_4_frontier_models_are_playing_a/
  (Reddit отдаёт 403 без авторизации; текст доступен в пересказе
  https://supermasao.exblog.jp/38771753, 2026-08-11).
* **Как устроено обучение** (там же): «Каждая модель записывает свои навыки как
  **code policies**, оценивает их в сравнении с другими агентами в production,
  сохраняет работающее и переписывает неработающее. Без fine-tuning и без вмешательства
  человека — учатся непрерывно, конкурируя в production. Мы уже видели, как они находят
  стратегии, которые никто не программировал вручную».
* **Почему метрика — XP**: «XP — самый ясный показатель того, может ли модель реально
  играть: он даётся за квесты, убийства, подземелья и эффективные маршруты, поэтому
  вознаграждается долгосрочное планирование, а не долбёжка кнопок». На момент поста
  лидер — Claude Opus 5, график часто меняет лидера.
* **Игра рассчитана на агентов**: «агентская модель читает исходный код игры, чтобы
  понять мир, и выводит мету из первых принципов». Именно это и делает наша линия
  (факты импортом из дерева игры, а не хардкодом).
* **Ранняя история агента** (тред r/ClaudeAI «Claude Plays World of ClaudeCraft»,
  2026-06-26, комментарии разработчика `singing_coach_ai`):
  - «мозг» — Claude Code (Sonnet): смотрит на состояние игры и порождает действия/реплики;
  - агент получает **информацию о состоянии игры и картинку состояния на 1 FPS**;
  - быстрые действия (бой) вынесены в **скрипты-"рефлексы"**, которые написал Opus и
    которые вызываются как инструменты: «так проще, потому что у него есть весь код игры»;
  - «мы сначала сделали это как QA-агента, а потом поняли, что это может быть зрелищно»;
  - «игру мы вообще-то начинали как reinforcement learning окружение»;
  - **на официальном сервере боты не приветствуются**: «у нас на сервере есть детектор
    ботов и баны, чтобы сохранить настоящий человеческий опыт; ИИ на основной сервер
    мы пока не пускаем». Отсюда: свой мир (docker compose, :8787) — правильное место
    для нашего агента, а не worldofclaudecraft.com.
* **Hermes** — открытый харнесс: https://github.com/NousResearch/hermes-agent (Python).
  Сам харнесс Арены **не опубликован**: его код не выложен, авторы зовут лаборатории
  писать в ЛС, чтобы поставить свою модель/харнесс на арену. То есть брать готовый код
  неоткуда — брать можно только архитектуру.

### Масштаб игры (GitHub API, 2026-09-18)

`levy-street/world-of-claudecraft`: 2258 звёзд, 716 форков, 380 открытых issues, MIT,
TypeScript, ветка `main`, размер репозитория ≈9.9 ГБ (поэтому полный чекаут тяжёлый и
в песочнице его держать нельзя), 55 контрибьюторов по данным поста Арены.
Поиск GitHub по `world-of-claudecraft` даёт 26 репозиториев; все, кроме одного, — форки
игры. Единственный нефрок-агентский репозиторий — `remontsuri/world-of-claudecraft-agent`
(Python, описание «autonomous RL bot, browser bridge, probes, logs (private backup)»,
ветка по умолчанию `backup`, 190 МБ). **Это не сторонний проект, а наш собственный
бэкап** — тот самый, чью fly-линию мы архивировали (см. `archive/`). Сторонних
агентов к этой игре, кроме Арены авторов, не найдено.

### Аналоги архитектуры (не для этой игры, но тот же рисунок «бридж + инструменты»)

* `ZachDeLong/shapez-agent`: мод внутри игры → WebSocket → `bridge-server.mjs` →
  `agent/run.mjs`; семь инструментов (`observe`, `place`, `place_many`, `connect`,
  `remove`, `run`, `list_buildings`); 140 проверок, которые не требуют запущенной игры;
  бридж usable и без агентского лупа (`GameBridge` — обычный API).
* `Claudeblox`: `game_bridge.py` (HTTP :8585) получает состояние из Roblox,
  `screenshot_game.py` отдаёт картинку модели, `AgentControl.lua` исполняет команды
  (GO_TO, INTERACT_WITH), `GameStateBridge.lua` шлёт позицию и ближайшие объекты раз в
  секунду, действия — через `execute_actions.py`/`pyautogui`.
* Общий рынок браузерных агентов (обзоры 2026): browser-use (перешёл на raw CDP),
  Stagehand (CDP-native, примитивы act/extract/observe), Playwright MCP (браузер как
  инструменты для любого MCP-клиента), Skyvern (vision-first). Это слой «как водить
  браузер», а не «как играть в MMO»: для нашей задачи он имеет смысл только в ветке C1
  (офлайн-страница), и даже там прямой CDP к `window.__game` дешевле и точнее, чем
  vision-агент.

### Что из этого следует для нашей линии

Совпадение по существу: их «навыки как code policies + оценка в production + переписывание
неработающего» — это наш `src/skills/` + `src/learn/tune.ts` + пороги, объявленные до
измерения. Отличия и, значит, наш план:

| Что у Арены | Что у нас сейчас | Разрыв → задача |
|---|---|---|
| живой сервер, несколько агентов одновременно | стенд in-process + headless-бридж (NDJSON) | A1.2/A1.3: WS-транспорт к :8787 |
| метрика — живой XP и лидерборд | целевая функция: квесты/убийства/смерти/уровень | A1.7: XP и лидерборд как метрика живого мира |
| самоулучшение в production, переписывание code policies | подбор порогов офлайн (train/val сиды, страж переобучения) | A7: самоулучшение в живом мире |
| сравнение агентов между собой | один агент, один прогон | A8: два наших агента на одном мире |
| VTuber-слой (голос, личность, стрим) | нет | не наша задача, если владелец не попросит |
