# World of ClaudeCraft — карта систем (игра) и стек агента

Составлено 2026-08-23 по авторским CLAUDE.md игры (src/**/CLAUDE.md — источник
истины по устройству игры) и фактическому коду агента в python/.

## Часть I. ИГРА (src/) — что есть и кто за что отвечает

Авторитетный принцип: **один сим, три хоста** — один и тот же `src/sim/` крутит
оффлайн-мир браузера, онлайн-сервер и RL-env. **Сервер авторитетен**: клиент только
рендерит; все исходы (бой, лут, квест-кредит, экономика) решает сервер.
**IWorld — единственный шов**: render/ui говорят только с фасадом `world_api/`.

| Система | Путь | Что там |
|---|---|---|
| Детерминированное ядро | `src/sim/` | Координатор Sim + системные модули за швом SimContext. Без DOM/Three. |
| Бой | `src/sim/combat/` | damage/heal/auras/casting/auto_attack/procs + per-class наборы (`fire_mage`, `frost_mage`, ...). |
| Контент (data-as-code) | `src/sim/content/` | Классы, способности, таланты, зоны, данжи, предметы, профессии, маунты, квесты. |
| Квесты | `src/sim/quests/quest_commands.ts` | accept/turnIn/abandon; turn-in требует: state=ready, правильный NPC в ~7yd, место под награду. |
| Профессии | `src/sim/professions/` | крафт, станки, workorder-квесты (наш kitchens/forge/loom отсюда). |
| Мобы/AI | `src/sim/mob/`, `sim/pet/` | спавн, AI, петы. |
| Социальное | `src/sim/social/` | гильдии, чат, почта. |
| Рендер | `src/render/` | Three.js. Читает мир, никогда не мутирует. |
| Ввод/камера | `src/game/` | input (контроллер движения!), click-to-move, keybinds. |
| HUD/UI | `src/ui/` | классический интерфейс, тултипы, квестовые диалоги. |
| Сеть | `src/net/` | ClientWorld (зеркало сервера), reconnect. `online.ts` — команды клиента. |
| Шов | `src/world_api/` | IWorld по фасадам на домен. |
| Клиент-энтри | `src/main.ts` | фиксирует сид мира; resolveMove (авто-прыжок через заборы — ТОЛЬКО в click-move ветке!). |
| Сервер | `server/` | Авторитетный мир, Postgres, auth. НЕ в этом репо-чекпоинте. |

Ключевое для агента:
- Движение игрока: `controller.move({forward/back/turnLeft/turnRight/strafe*/jump})`
  → `input.setControllerMoveInput` → `resolveMove` → sim.moveInput. jump валиден
  как флаг moveInput (MOVE_FIELDS включает 'jump').
- Заборы хопабельны (низкий рельс), но авто-прыжок живёт только в click-move;
  наш navigateToCoord должен слать jump сам при застревании.
- `findPlayerPath` (A* игры) приватен — мосту недоступен, обходим сами.

## Часть II. АГЕНТ (python/ + bridge) — конечная структура

```
ИГРА (Chrome, worldofclaudecraft.com)
  ▲ CDP :9222
  │
browser_bridge.cjs (:8791)          ← HTTP-мост: snapshot / step / navigate / respawn
  src/bridge/game_client.cjs        ← puppeteer-core, переподключение
  src/bridge/snapshot.cjs           ← плоский obs: player/nearby/quests/kills...
  src/bridge/actions.cjs            ← applyAction(idx 0..12) + navigateToCoord
  ▲ HTTP JSON
  │
python/browser_env.py               ← BrowserEnv: step/navigate/_post
python/hierarchical_env.py          ← SKILLS контракт (0 farm ... 12 craft_item)
python/agent.py                     ← Agent._cycle: decide→skill→verify→learn
  ├─ python/policy.py               ← GoalManager: кандидаты фазы + softmax по Q
  ├─ python/memory.py               ← Q-таблица TD(0) + WorldMemory (гиверы/вендоры)
  ├─ python/reward.py               ← outcome_reward из дельт мира
  ├─ python/verifiers_py.py         ← честные вердикты SUCCESS/FAILURE/INCONCLUSIVE
  ├─ python/quest_skill.py          ← составные скиллы (turn_in = nav+turnInQuest)
  └─ python/goal_fsm.py             ← FSM фаз: NO_QUEST→...→TURN_IN (+R1/Fix5 демотации)
  │
python/play_autonomous.py           ← runner: цикл, метрики, логи
  ├─ WOC_BRAIN=on → llm_brain.py    ← Qwen3.6-35B :8081 (json_schema strict, enum целей)
  │   ├─ brain_glue.py              ← payload мира {quest, ready_quests, hp,...} + apply_decision
  │   └─ episodic.py                ← эпизодическая память попыток (jsonl)
  ├─ self_reflection.py             ← журнал выводов → policy-хинты (TTL 20 мин)
  ├─ replay_buffer.py               ← rare-event приоритет + train_from_replay
  └─ strategy_memory.py / goal_state.json
```

## Поток решения (после всех фиксов 2026-08-23)

1. `goal_fsm.update_from_world(ws)` — FSM синхронизируется с живым questLog
   (стейл TURN_IN демотируется в DO_OBJECTIVE — Fix5).
2. `brain.should_consult()`? — только переходы: смена фазы/цели, ≥3 фейла,
   новый квест, каждые 50 шагов.
3. Да → `build_brain_payload`: quest + **ready_quests** + hp + giver_distance +
   recent_failures (episodic) + уроки SelfReflection → Qwen → `{goal}` (enum).
4. `apply_decision` валидирует и ставит цель FSM. SURVIVE мапится в HEAL.
5. `policy.decide()` выбирает СКИЛЛ внутри фазы (Q-learning + survival gates).
6. Skill исполняется мостом; верификатор меряет дельту мира; reward = дельты +
   вердикт; всё пишется в autonomous_log.jsonl + episodic_log.jsonl.
7. LLM видит неудачи в следующий раз (recent_failures) — петля рефлексии замкнута.

## Известные ограничения (честно)

- Авто-прыжок через заборы в navigateToCoord ещё не включён (Fix6 в планах):
  сейчас анти-stick ±120° зигзаг, против длинного забора слаб.
- LLM вызывается не каждый шаг (латентность ~1–7с) — между вызовами правит
  закешированная цель; экстренный HEAL решается policy-гейтом независимо.
- Сервер молча отклоняет часть команд (turn_in без NPC рядом): единственная
  правда — дельта questLog, верификатор уже это учитывает (Fix2).
