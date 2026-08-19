# WoC-Ragent — Project Memory

> Актуальное состояние на 2026-08-19. Переписано полностью (старого memory.md не было).
> Репозиторий: `D:\world-of-claudecraft` — CLONE `levy-street/world-of-claudecraft`
> (origin, публичная игра) + наш агент-код. Backup-remote: `remontsuri/world-of-claudecraft-agent`
> (ветка `mine/backup`, локальная ветка `backup`).

## Статус (коротко)
- Agent может: observe → policy → farm → реальный combat Sim → kill/death → reward → TD memory → следующее решение.
- Цепочка `navigate → targetEntity → startAutoAttack → mob dies` ПОДТВЕРЖДЕНА живым smoke-тестом (2×).
- Длинный autonomous/PPO-run НЕ запускался (решено: сначала smoke, потом run).
- Бридж остановлен по приказу пользователя; перс выведен в стартовую локацию (zone1, -5,-52) и замер.

## Git / коммиты
HEAD (`mine/backup`): `7de297e05`
Цепочка исправлений:
- `ead45a23d` — farm navigation: turn geometry, убран блокирующий stop(), chase+attack loop
- `ea31f4be6` — P0/P1: cross-check bridge/verifiers против оригинального game API
- `ebd835636` — respawn-at-corpse order, honest heal/gather/equip/buy, end-to-end ok:false guard
- `7de297e05` — combat re-face fix + smoke_combat.py
Рабочий флоу: правки → `git commit` → `git push mine backup`.

## Структура репозитория
```
D:\world-of-claudecraft\
├── browser_bridge.cjs        # HTTP-мост (:8791) к живому Chrome (CDP :9222)
│                             #   cmdQueue (1 live browser, сериализация команд)
│                             #   action idx 0..9, respawn, snapshot, navigate, raw_move, explore
├── python/
│   ├── agent.py              # GoalManager loop: observe → decide → skill → cap API
│   ├── policy.py             # tabular policy, SKILL_INDEX = enumerate(SKILLS)
│   ├── browser_env.py        # BrowserEnv — I/O к bridge (_require = ok:false guard)
│   ├── memory.py             # ExperienceStore (TD-память)
│   ├── reward.py             # reward-функция
│   ├── smoke_combat.py       # ЧЕСТНЫЙ smoke: navigate→target→autoattack→kill
│   └── *_nav_report_*, bc_nav_*, experience_*.json   # диагностика/логи
├── tools/adapter_v1/
│   ├── world_facade.ts       # LiveWorldFacade — ЧЕСТНЫЙ адаптер к window.__game
│   ├── known_points.ts       # статические giver/vendor координаты
│   └── types.ts              # контракт WorldFacade
├── src/                      # ИСХОДНИКИ ИГРЫ (levy-street, не наш код)
│   ├── sim/sim.ts            # Sim: player, entities, harvestNode, equipItem, buyItem, targetEntity
│   ├── sim/combat/auto_attack.ts  # startAutoAttack/updatePlayerAutoAttack — swing gate
│   ├── sim/targeting.ts      # targetEntity (ставит p.targetId)
│   ├── sim/items.ts          # useItem (potion/heal)
│   ├── sim/content/graveyards.ts  # graveyards (gy_willowfen, gy_vale_chapel...)
│   └── world_api/combat.ts   # IWorldCombat: resurrectAtCorpse/releaseSpirit/resurrectAtSpiritHealer
├── dist-tools/               # архивные/доставочные варианты (не трогать)
├── audit_pack*/              # аудит-копии (не трогать)
└── _*.cjs                    # временные зонды (удалять по необходимости)
```

## Маппинг action idx (browser_env.py: AGENT→bridge)
`0 farm, 1 loot, 2 accept_quest, 3 turn_in_quest, 4 sell_junk, 5 gather, 6 craft, 7 heal, 8 equip, 9 buy`
- SKILLS (policy.py) = тот же список; SKILL_INDEX = enumerate(SKILLS).

## Capability-статус (2026-08-19, честно)
- `0 farm` ✅ реальный combat (targetEntity+startAutoAttack+re-face)
- `1 loot` ✅ loot трупа
- `2 accept_quest` ✅ sim.interact у quest-giver
- `3 turn_in_quest` ✅ sim.interact у giver
- `4 sell_junk` ✅ sim.sellAllJunk
- `5 gather` ✅ sim.harvestNode (node в радиусе 60)
- `6 craft` ⚠️ honest NO-OP (`sim.craft` undefined в клиенте) — в списке SKILLS, policy учит waste
- `7 heal` ✅ код корректен (`sim.useItem` на potion), НО требует potion в сумке
- `8 equip` ✅ sim.equipItem (gear с equipSlot)
- `9 buy` ✅ код корректен (`sim.buyItem(npcId, 'minor_healing_potion')`), НО требует trade-vendor рядом

### Ограничения heal/buy (важно)
- В СТАРТОВОЙ ЗОНЕ (zone1) НЕТ trade-vendor'а с potion. `vendorItems` у NPC пуст (len 0).
  Проверено: `sim.buyItem` не бросает исключение, но ничего не покупает (server-authoritative: нет в ассорте).
- Реальные trade-vendors (vendor:true) — в zone3: Quartermaster Bree (x=-5,z=668),
  Armorer Hode (x=-2,z=672), и т.д. (см. known_points.ts).
- Значит heal-цепочка (buy→heal) работает ТОЛЬКО у trade-vendor в zone3.
- smoke_heal.py написан, но требует перса рядом с trade-vendor (не в стартовой зоне).
- Позиция перса server-authoritative: прямая телепортация в zone3 не держится (откат на тик).

## Respawn (browser_bridge.cjs: respawn handler)
Порядок по IWorldCombat: `resurrectAtCorpse()` (у тела, без штрафа, если в радиусе) → если ВСЁ ЕЩЁ dead → `releaseSpirit()` + `resurrectAtSpiritHealer()` (graveyard path).
Старый порядок (releaseSpirit → corpse) был неверен: после releaseSpirit игрок уже не у тела.

## Combat (почему работает)
- `startAutoAttack` (auto_attack.ts) берёт уже существующий `p.targetId` (его ставит targetEntity) и вкл. autoAttack.
- Swing идёт в `updatePlayerAutoAttack` на tick, НО только если `d <= MELEE_RANGE (5yd)` И `facingDiff <= MELEE_ARC (2.2rad)`.
- Баг был: farm не держал facing → swing не попадал → перс бил вхолостую. Фикс: re-face в attack-ветке.

## Smoke-тест (python/smoke_combat.py)
Запуск (бридж поднят):
```
cd D:\world-of-claudecraft\python
PYTHONPATH="" D:\woc-llm\therock-test\Scripts\python.exe smoke_combat.py
```
Критерий PASS = моб dead (hp→0/dead/lootable) после navigate→target→autoattack.
Логирует: player_pos, mob_pos, distance, mob_hp_before/after, kills_before/after, player_hp, deaths.
Последний честный прогон:
```
navigate: dist 38.9 -> 28.5yd
mob_hp: 66 -> 0, dead=True
player_hp: 44 -> 219 (выжил)
PASS: mob died via Sim combat
```

## Autonomous self-play (2026-08-19)
- `agent.py` `run(n_steps=3000, save_every=100)`: долгий автономный цикл.
  Сохраняет ExperienceStore каждые 100 шагов (resumable). Stop движения на выходе.
- Агент балансирует ВЕСЬ скилл-сет через выученную policy (НЕ скриптованный бот):
  quest/loot/sell/farm/heal/buy/equip/explore.
- Подтверждено (run 200 шагов): Q в боевом бакете выросли
  (return_to_giver +4.2, farm +3.4, accept_quest +3.2, loot +3.2, sell_junk +3.0).
  `farm` дал первый positive reward (+0.32) — бой засчитался.
- Ограничение: в стартовой зоне мобов/vendor'ов мало → explore выводит агента
  к zone3 (Thornpeak, x≈4,z≈664), где buy/heal/equip становятся доступны.
- Запуск: поднять бридж (`node browser_bridge.cjs`), затем
  `cd python && PYTHONPATH="" /d/woc-llm/therock-test/Scripts/python.exe agent.py`

- `craft` (idx=6) невозможен: `sim.craft` undefined в живом клиенте.
- `buy` (idx=9) требует vendor+itemId; bridge только открывает vendor.
- Позиция перса server-authoritative: прямая запись `p.pos.x/z` НЕ держится (откатывается на след. тик). Переместить перса можно только через `controller.move` (навигация) или respawn.
- Heal требует реальной potion в сумке; если нет — honest no-op (policy учит waste).

## Запуск бриджа (background падает с "stdin is not a tty" в MSYS — это ок, бридж жив)
```
cd D:\world-of-claudecraft && node browser_bridge.cjs
# слушает :8791; подключается к Chrome CDP :9222 (game-tab worldofclaudecraft)
```

## Что НЕ делать
- Не трогать `tools/adapter_v1/world_facade.ts` obs/Sim/reward/PPO (это честный адаптер, отдельный слой).
- Не убивать running bg-задачи без нужды.
- Не выдумывать PASS: verify-before-done (прямой probe/живой smoke).
