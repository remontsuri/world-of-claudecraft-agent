# Порт моста на Java — объём и план

Цель: мост (`:8791`) и агент — на Java, без Node-прослойки.
Пока порт не закончен, работает переходная схема: `BridgeServer` (Java) поверх
Node-моста через `UpstreamBackend` — контракт снаружи один и тот же.

## Что уже есть в Java (проверено сквозным прогоном)

| Компонент | Файл | Состояние |
|---|---|---|
| HTTP-сервер контракта (`snapshot/step/navigate/raw_move/respawn/explore`) | `bridge/BridgeServer.java` | ✅ есть, слушает заданный порт, отдаёт `{ok, info}` |
| Прослойка на существующий мост | `bridge/UpstreamBackend.java` | ✅ есть |
| Голосование с CDP | `bridge/CdpBackend.java` | ❌ заглушка, падает с внятным текстом |
| Агент (цикл, фазы, навыки, память) | `core/AgentCore.java`, `core/SkillExecutor.java`, `arbitration/` | ✅ есть |
| Разбор снимка в `WorldState` | `env/SnapshotMapper.java` | ✅ есть |

## Что нужно портировать (в порядке зависимостей)

| # | Модуль Node | Строк | Что делает | Сложность порта |
|---|---|---:|---|---|
| 1 | `src/bridge/game_client.cjs` | 151 | CDP: поиск вкладки по `/json`, WS-соединение, `Runtime.evaluate` с ожиданием по id, recovery зависшей вкладки | средняя: транспорт, 1:1 на Java-WebSocket |
| 2 | `src/bridge/cmd_queue.cjs` | 77 | ограниченная очередь команд + watchdog на команду (farm держит вкладку ~17 с), продолжение только после `health()` | низкая: логика на 77 строках |
| 3 | `src/bridge/snapshot.cjs` | 456 | построение ПЛОСКОГО снимка внутри страницы (`window.__game`): игрок, nearby, квесты (active/ready/done), `turnInNpc`, `quests_done`, кулдаун квестов | средняя: код исполняется в браузере, на Java переносится как строковый ресурс, но требует точного соответствия |
| 4 | `src/bridge/actions.cjs` | 968 | 13 навыков: farm/loot/accept/turn_in/sell/gather/craft/heal/equip/buy/каст/craft_item, включая chase, `navigateToCoord`, gather с pathing, fence-hop | высокая: самая большая часть, много игровых деталей |
| 5 | `src/bridge/heading.cjs`, `fence_hop.cjs`, `quests_done.cjs` | 145 | доворот курса, перепрыгивание заборов, честный счётчик сданных квестов (Set) | низкая |
| 6 | `browser_bridge.cjs` | 145 | HTTP-обвязка, таблица dispatch, graceful shutdown | в Java уже сделано (`BridgeServer`) |

**Итого к переносу: ~1800 строк Node, из них ~1000 — игровая логика навыков.**

## Рекомендуемый порядок (проверяемый на каждом шаге)

1. **CDP-транспорт** (`game_client.cjs` → `CdpClient.java`): поиск вкладки, id-сопоставление
   ответов, таймауты, переподключение. Проверка: полигон-эмулятор CDP (fake CDP-сервер),
   подающий заранее известные ответы — без браузера.
2. **Снимок** (`snapshot.cjs` → ресурс `snapshot.js` + `SnapshotMapper`): сравнение
   «Java-мост» и «Node-мост» на одинаковой странице — поля должны совпадать.
3. **Простые навыки** (`farm` одной целью, `loot`, `accept_quest`, `turn_in_quest`, `heal`,
   `equip`, `buy`, `sell_junk`) — с проверкой «вне радиуса взаимодействия не зовём».
4. **Сложные потоки** (`navigate` с pathing/chase, `gather`, fence-hop, каст) — переносить
   последними: они самые «игровые» и чаще всего правятся.

## Критерий готовности порта

`tools/run_e2e.sh` проходит против **реального** моста на Java (без Node),
и на реальной игре повторяется цепочка `accept → farm ×6 → loot → turn_in`.
