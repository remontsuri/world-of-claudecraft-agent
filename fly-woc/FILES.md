# Карта файлов fly-линии

Сгенерировано из кода. Назначение берётся из docstring/комментария самого файла —
то есть из того, что автор написал для себя, а не из пересказа.

## `fly-woc/*.py` — активная линия (15 файлов)

| Файл | Тип | Строк | Назначение |
|---|---|---|---|
| `agent.py` | модуль | 31 | Trainable readouts. The connectome is never trained; only these nets are. FlyBrainReadout: DN activities -> actor/critic MLPs (the experimental agent). MLPControl:      raw game observations -> actor/ |
| `build_circuit.py` | запускаемый | 277 | Build a bounded, measured MaleCNS v1.0 circuit for world-of-claudecraft. Selection uses ANATOMY ONLY, never game outcomes (Fly Dino protocol, flyjump scripts/build-connectome.py): 1. Retain every desc |
| `build_full_circuit.py` | модуль с main | 105 | build_full_circuit.py — собрать нормализованный circuit.json для полного MaleCNS 211K. |
| `check_io.py` | модуль | 58 | I/O sanity check: does the game observation actually drive the circuit? fly-craftax M2/M3 lesson: their retina stayed silent until a lamina bias was added, and an agent can score with zero visual cont |
| `device_utils.py` | модуль | 120 | device_utils.py — единственное место, где выбирается устройство вычислений. Порядок выбора: аргумент --device → переменная WOC_DEVICE → cuda → mps → cpu. Почему отдельный модуль: прежний код выбирал у |
| `env_robust.py` | модуль | 204 | env_robust.py — make long WoC training runs survive a dying env server. Why this exists (the crash we hit on Windows): WoWClassicEnv spawns the node server with ``stderr=subprocess.DEVNULL``, so when  |
| `fly_llm.py` | модуль | 549 | LLM-кортекс поверх замороженного коннектома: выбирает ЦЕЛЬ (квест/mode/go), коннектом исполняет. Вето правил, строгая JSON-схема, бэкенды fake/server (llama.cpp json_schema), неблокирующий фон. Тесты — tools/test_fly_llm.py |
| `fly_lm_brain.py` | модуль | 390 | «LLM в мозгу»: двусторонняя связка с коннектомом — сводка активности 82 DN для промпта, калиброванный (по измеренному dDN/dканал) проектор «состояние LLM → сдвиг 13 каналов», границы по группам каналов, контроль disconnected (ровно нулевой сдвиг) |
| `fly_brain.py` | модуль | 467 | Frozen MaleCNS circuit engine + engineered sensory drive (world-of-claudecraft). Dynamics follow the Fly Dino v2 protocol (flyjump src/lib/connectome.ts): signed, normalized, leaky-tanh rate units, 3  |
| `flybrain_8k_gpu.py` | модуль | 119 | FlyBrain8KGPU — оптимизированный 8K MaleCNS subset на GPU (CSR format). |
| `flybrain_full.py` | модуль | 103 | FlyBrainFull — полный MaleCNS 211K нейронов на GPU с rate-based propagation. |
| `live_agent.py` | запускаемый | 300 | Live MaleCNS/Fly controller for the real WoC 61-action wire. The committed PPO checkpoint was trained against src/sim/obs.ts ACTIONS.  The legacy online BrowserEnv.step() API is a 10-skill capability  |
| `obs_layout.py` | модуль | 326 | obs_layout.py — раскладка observation-вектора, выведенная из его длины. Игра считает размер obs так (`src/sim/obs.ts: obsSize()`): obsSize() = 16 + ABILITY_SLOTS * 2 + 9 + NEARBY_MOBS * 6 + 5 + QUEST_ |
| `progress_eval.py` | запускаемый | 242 | progress_eval.py — прогресс-метрики мухи в реальном офлайн-симе WoC. Отвечает на вопрос «играет ли муха», а не «какой у неё reward»: reward можно набрать стоя на месте (timePenalty отрицательный, но q |
| `quest_oracle.py` | запускаемый | 293 | quest_oracle.py — куда идти по квесту, не заглядывая в Sim. В obs игры 224 квеста лежат парами (state, progress), порядок — `QUEST_ORDER` из `src/sim/data.ts`, он же порядок, в котором их пишет `src/s |
| `train.py` | запускаемый | 612 | Train the fly-brain readout on world-of-claudecraft with PPO, then evaluate it against the full control battery and export every rollout as evidence. Architecture (identical pattern in Fly Dino v2, fl |

> Аудит всей линии на ошибки и цена горячего пути (с числами «до/после»):
> `fly-woc/AUDIT-2026-09-17.md`.

## `fly-woc/tools/` — проверки и сборка (22 файлов)

| Файл | Строк | Что делает |
|---|---|---|
| `accel_m1_m3.sh` | 100 | # accel_m1_m3.sh — ступени к M1–M3. Каждая следующая запускается только после зелёной |
| `dump_quest_oracle.ts` | 70 | — |
| `env_robust.py` | 16 | env_robust.py (в tools/) — ЗАГЛУШКА для тестов без игры. Настоящий env_robust.py поднимает node-сервер игры, следит за его падением и перезапускает. Здесь — простое перенаправление на заглушку окружен |
| `fake_wow_env.py` | 64 | fake_wow_env.py — заглушка игрового окружения для тестов БЕЗ игры и node. Зачем: train.py импортирует wow_env на уровне модуля, поэтому проверять устройство (мозг + readout + маска + оракул) без чекау |
| `gpu_check.py` | 107 | gpu_check.py — проверка устройства на ЭТОЙ машине: что выбрано, что пойдёт в дело. Запускать там, где предполагается GPU (Windows/Linux, torch с CUDA): python tools/gpu_check.py                      # |
| `make_control_graph.py` | 215 | make_control_graph.py — контроли топологии для MaleCNS-схемы (свой, без чужого кода). Зачем: утверждение «важна именно топология коннектома» проверяемо ТОЛЬКО против схемы с той же плотностью и теми ж |
| `make_quest_oracle.sh` | 47 | !/usr/bin/env bash |
| `probe_game_shape.ts` | 31 | — |
| `record_replay.py` | 180 | record_replay.py — записать прогон мухи в живой игре, чтобы его можно было УВИДЕТЬ. |
| `render_replay.py` | 324 | render_replay.py — превратить запись прогона (record_replay.py) в одну HTML-анимацию. |
| `run_checks.sh` | 18 | !/usr/bin/env bash |
| `serve_viz.py` | 115 | Показать наши клетки в Neuroglancer — чужом готовом вьюере, без своего рендера. |
| `smoke_llm_goal.py` | 131 | smoke_llm_goal.py — живая проверка «киборга» на настоящей маленькой модели. |
| `test_control_graph.py` | 186 | test_control_graph.py — приёмка контролей топологии без игры, GPU и сети. Сравниваем контроль не с полной схемой, а с её же подграфом-источником (`--swaps 0` даёт ровно ту выборку узлов, с которой пот |
| `test_device.py` | 258 | test_device.py — приёмка устройства вычислений: GPU-путь там, где он должен быть. Проверяем не «есть ли cuda» (в песочнице её нет), а корректность плумбинга: 1) resolve_device: auto -> лучшее доступно |
| `test_fly_llm.py` | 287 | test_fly_llm.py — приёмка «киборга»: LLM выбирает цель, коннектом рулит. |
| `test_llm_in_brain.py` | 210 | test_llm_in_brain.py — приёмка двусторонней связки: вклад в DN ≥3 %, чтение мозга в промпте, границы каналов, разрыв = строго ноль, калибровка измерена |
| `reservoir_experiment.py` | 177 | reservoir_experiment.py — повтор контроля FLM: предсказание следующего состояния мира по состояниям мозга (reservoir) против прямого входа и сырых obs |
| `analyze_coupling.py` | 108 | analyze_coupling.py — расхождение траекторий «связка vs разрыв», метрики игры, отчёт связки из meta |
| `test_obs_layout.py` | 178 | test_obs_layout.py — раскладка obs не должна зависеть от версии игры. Сборки сняты исполнением игрового кода (tools/probe_game_shape.ts) на тегах: obs = 60 + 2*способности + 2*квесты (+3, если есть хв |
| `test_parallel_envs.py` | — | параллельный шаг по средам: корректность (reward/done/obs совпадают поэлементно с последовательным прогоном) и выигрыш (8 сред с задержкой 20 мс → 7.7x). У заглушки окружения для этого появилась ручка `WOC_FAKE_LATENCY_MS` |
| `test_quest_oracle.py` | 154 | test_quest_oracle.py — приёмка таблиц оракула без игры, GPU и сети. Что проверяется у каждой data/quest_oracle*.json: 1) схема: game/order/quests; ключи game и квестов — как у соседних таблиц; 2) ариф |
| `verify_provenance.py` | 201 | verify_provenance.py — «наш мозг — это правда MaleCNS?» Проверка по исходным данным. |
| `viz_export.py` | 258 | Сцены Neuroglancer для нашей схемы: наши клетки внутри настоящего MaleCNS. |
| `wow_env.py` | 13 | wow_env.py (в tools/) — ЗАГЛУШКА игрового окружения для тестов. Настоящий wow_env живёт в чекауте игры (python/wow_env.py) и запускает node-симу. Этот файл даёт тот же интерфейс, чтобы можно было запу |

## `src/fly_brain/` — ядро и старые эксперименты (14 файлов)

| Файл | Тип | Строк | Назначение |
|---|---|---|---|
| `__init__.py` | модуль | 7 | src/fly_brain package — Fly brain integration for World of Claudecraft. |
| `agent.py` | модуль | 31 | Trainable readouts. The connectome is never trained; only these nets are. FlyBrainReadout: DN activities -> actor/critic MLPs (the experimental agent). MLPControl:      raw game observations -> actor/ |
| `connectome.py` | модуль | 99 | connectome.py — load FlyWire v783 connectivity matrix and build CSR weights. |
| `connectome_dashboard.py` | запускаемый | 143 | connectome_dashboard.py — Connectome-OS style live dashboard for the fly brain. Shows live spike raster + group rates from the running LIF engine. Pattern from Connectome-OS: watch structure as it fir |
| `connectome_philshiu.py` | модуль | 184 | Wrapper around philshiu/Drosophila_brain_model — the real Drosophila connectome. Uses Brian2 LIF simulation with FlyWire v783 connectivity (138K neurons, 15M synapses). Not used for action selection ( |
| `da_stdp.py` | модуль | 188 | da_stdp.py — dopamine-modulated STDP for KC→MBON plasticity. Implements DA-STDP learning rule: ΔW = η · DA(t) · exp(-|Δt|/τ) · Sign(Δt) Where: - DA(t) = dopamine concentration (from PPL101/PAM activat |
| `engine.py` | модуль | 264 | engine.py — LIF neural simulation engine for FAFB 138K (sparse). Optimized for ROCm/CUDA. Uses sparse matrix multiplication for recurrent connections. |
| `fly_brain.py` | модуль | 138 | FlyBrain — high-level adapter wrapping BrainEngine for train_fly_ppo.py. Provides the interface expected by the training script: - FlyBrain(device) -> loads MaleCNS, initializes engine, resolves DN in |
| `fly_ppo_agent.py` | модуль | 210 | fly_ppo_agent.py — Full PPO-ready FlyBrain agent for WoC. Architecture (from fly-craftax + Fly Dino + FLYT3 patterns): obs → sensory_encoder(obs) → LIF steps on FROZEN MaleCNS → DN activity → actor/cr |
| `motor_decoder.py` | модуль | 160 | motor_decoder.py — decode descending neuron spikes to WoC actions via WTA. Hard-coded readout channels (from baseline noise test, FAFB v783): - Neuron 105779 (5.0 Hz) → DNg13_LEFT  → TURN_LEFT  (2) -  |
| `sensor_adapter.py` | модуль | 59 | sensor_adapter.py — map WoC game observations to fly photoreceptor inputs. |
| `trainable_readout.py` | модуль | 119 | trainable_readout.py — trainable readout over fixed MaleCNS connectome. Pattern from Fly Dino (cobanov/flyjump), fly-craftax (liuzihe02), FLYT3 (seanphan): the connectome wiring is FIXED; only a small |
| `woc_brain_env.py` | модуль | 275 | woc_brain_env.py — Gymnasium env integrating LIF brain with WoC game. Full pipeline: WoC observation → SensorAdapter (photoreceptors) → BrainEngine (LIF 138K) → MotorDecoder (WTA) → WoC action |
| `woc_features.py` | модуль | 82 | woc_features.py — engineered WoC observation features for fly-brain. Pattern from Fly Dino v2: 8 structured game features mapped to visual cell types. For WoC we use 8 features covering: HP, mob dista |
