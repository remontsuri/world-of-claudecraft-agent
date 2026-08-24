# Задача D: корень «квест исчез из ready, но quests_done не вырос»

Ты — со-диагност. Работаем по методу systematic-debugging: **корень до фикса**.
Стек ВЫКЛЮЧЕН (мост и агент не запущены) — ничего не запускай.

## Наблюдение (живой замер, только что)

Персонаж стоял в 4.5 yd от гивера, квест `q_prof_workorder_loom` был в `ready`
(6/6). Вызвали сдачу через мост (`{"action":"step","idx":3,
"questId":"q_prof_workorder_loom"}`). Результат:

```
ДО:    quests_done = 0 | ready = ['q_prof_workorder_loom']
ПОСЛЕ: quests_done = 0 | ready = []
active(10)  ready(0)  done(0)
xp: 1242 (не изменился)   copper: 6341
q_prof_workorder_loom в active? False
```

Квест **исчез из всех трёх ведёр**, счётчик НЕ вырос, награды нет.

## Что я уже установил (проверь и продолжи)

1. `src/sim/quests/quest_commands.ts:399+` (`turnInQuestCore`) при УСПЕХЕ делает:
   - `meta.questLog.delete(questId)` (строка ~433)
   - `meta.questsDone.add(questId)` (строка ~435)
   - `meta.copper += quest.copperReward` (если >0)
   - `ctx.grantXp(quest.xpReward, meta)`
   - `ctx.emit({ type: 'questDone', ... })`
   - арминг cadence-окна для work-order

2. `q_prof_workorder_loom` (zone1.ts:1399-1417): `repeatable: true`,
   `xpReward: 100`, `copperReward: 15`, `repeatCadenceTicks: WORK_ORDER_CADENCE_TICKS`,
   objectives: `collect spider_silk × 6`.

3. Мост берёт счётчик так (`src/bridge/snapshot.cjs:233`):
   ```js
   quests_done: (typeof (g.online && g.online.questsDone) === 'number')
     ? g.online.questsDone : done.length,
   ```
   То есть в ОНЛАЙН-режиме читается `g.online.questsDone`, а не состояние сима.

## Вопросы — ответь по КОДУ, с цитатами файл:строка

**D1.** Сдача РЕАЛЬНО произошла или сервер отказал? Ищи в `src/net/online.ts`:
как клиент отправляет turn-in на сервер, что приходит в ответ, обновляется ли
`online.questsDone`. Возможно, клиент отправил команду, сервер её отверг, а
локальный questLog всё равно очистился (рассинхрон). Назови конкретный путь.

**D2.** Почему квест исчез и из `ready`, и из `active`, и НЕ появился в `done`?
Смотри `src/bridge/snapshot.cjs:130-150` (как раскладываются ведра) и
`src/net/online.ts` (что клиент хранит в своём questLog в онлайне). Возможно,
`done` наполняется из другого источника, чем `active`/`ready`.

**D3.** Cadence work-order: после сдачи повторяемый квест уходит в кулдаун
(`cadenceBlockedKeys`, `WORK_ORDER_CADENCE_TICKS`). Может ли квест из-за этого
исчезнуть из всех ведёр, но `questsDone` вырасти ПОЗЖЕ (асинхронно от сервера)?
Найди `WORK_ORDER_CADENCE_TICKS` (значение в тиках и в секундах) и правило.

**D4.** Что должно быть НАДЁЖНЫМ признаком успешной сдачи для нашего
верификатора? Сейчас `verifiers_py.py` считает успехом переход квеста
`ready -> done` ИЛИ рост `quests_done`. Оба сигнала здесь не сработали.
Предложи признак, который в ОНЛАЙН-режиме честно отличает успех от отказа
(варианты: событие `questDone` в потоке событий; рост `xp`; рост `copper`;
исчезновение из questLog при одновременном ответе сервера ok; что-то ещё).
Обоснуй по коду.

**D5.** Есть ли в онлайне отдельная команда сдачи (не `sim.turnInQuest`)?
Проверь `src/net/online.ts` на `turnIn`/`questTurnIn`/`cmd:'turnin'` и как её
надо звать из моста. Возможно, мост звал офлайн-путь, который в онлайне только
локально мутирует состояние без серверного подтверждения.

## Ограничения

- НИЧЕГО не запускай (ни мост, ни агента, ни браузер). Только чтение кода.
- Код не меняй.
- Экономь итерации: grep по ключевым словам, читай только нужные фрагменты.
- Если чего-то нет — пиши «не найдено», не выдумывай.

## Формат ответа

JSON: `findings` (массив по D1-D5: `{id, answer, evidence, confidence}`),
`root_cause` (одно предложение), `reliable_success_signal` (что проверять),
`fix_location` (файл:функция, где править).
