# Fly × World of Claudecraft — протокол эксперимента

**Задача:** заставить муху (замороженный коннектом MaleCNS + обучаемый readout) полноценно играть в world-of-claudecraft (headless-окружение levy-street/world-of-claudecraft).

**Дата:** 2026-09-14 · **Training seed:** 20260914 · **Env:** `flydino`-style протокол адаптирован под WoC

## Архитектура (паттерн Fly Dino v2 / fly-craftax / FLYT3)

```
obs(607) → 13 engineered features → FROZEN MaleCNS circuit (8 835 клеток,
1 874 865 рёбер, leaky-tanh, 3 итерации/решение) → 82 DN-активности →
обучаемый readout (MLP 82→64→61, PPO) → Discrete(61)
```

Обучается **только readout**. Граф, знаки синапсов, нормировка, drive-маппинг и динамика фиксированы. Активность безразмерна — это не спайки и не мембранные потенциалы.

## Окружение

- `WoWClassicEnv` (python/wow_env.py из levy-street/world-of-claudecraft) поверх headless Node-симуляции (`npm run build:env` → esbuild-бандл `dist-env/env_server.cjs`), та же детерминированная TS-симуляция, что и в браузерной игре.
- obs = 607 float32: self(16) | abilities(48×2) | target(9) | mobs(5×6) | interactable(5) | quests(224×2) | paladin(3).
- actions = Discrete(61): noop, движение ×7, target_nearest, attack, ability_1..48, interact, stop, eat_drink.
- frame_skip 5 (4 решения/сек игры), max_steps 1200 (≈5 мин игры), награды сервера по умолчанию (xp 0.01, damage 0.002/−0.001, kill 0.2, death −5, quest 0.5/5, levelup 2).

## Коннектом и отбор схемы (только анатомия, до обучения)

Данные: MaleCNS v1.0 minconf 0.5, **traced-only** edges (485 MB). SHA-256 всех трёх файлов и графа — в `data/manifest.json` (annotations и NT совпадают с manifest Fly Dino; edges-хеш отличается, т.к. traced-only).

Отбор DN-центрический двуххоповый (в отличие от Fly Dino, где 80 клеток от 8 LC-типов):
1. Все 1 314 descending neurons.
2. P1: топ-4 000 пресинаптических партнёров DN по контактному весу.
3. P2: топ-4 097 партнёров P1.
4. Все измеренные рёбра внутри V сохранены (включая рекуррентные и 1-контактные). Ничего не синтезировано.

**Итог: 8 835 клеток / 1 874 865 рёбер / 15 800 512 контактов.** Это circuit subset, не полный граф — помечать везде.

### Входы (13 каналов × 4 клетки, Fly Dino-ранжирование по прямым контактам на DN)

| # | Фича obs (индекс) | Тип клеток |
|---|---|---|
| 0 | hp ratio [0] | JO-FV |
| 1 | resource ratio [1] | GNG423 |
| 2 | in combat [11] | BM_Vib |
| 3 | gcd ready [8] | AN19A018 |
| 4 | target exists [112] | LC4 |
| 5 | target dist [115] | LPLC2 |
| 6 | target hp [113] | LPLC1 |
| 7 | target bearing sin [116] | LPLC4 |
| 8 | target bearing cos [117] | LT51 |
| 9 | nearest mob dist [121] | LLPC1 |
| 10 | mob aggro fraction [126::6] | PVLP122 |
| 11 | ability readiness [16:112:2].mean | LgLG3 |
| 12 | quest progress [157:604:2].mean | BM_Taste |

Маппинг фич→типы — инженерный, без биологической интерпретации (формулировка Fly Dino v2). Классические типы Fly Dino LC9/LC11/LC15-LC22 в traced-only потеряли трейснутые входы, заменены на измеренные DN-проецирующие типы. Драйв: `u = 2·(f − 0.5)`.

### Выходы: 82 DN
Топ-64 по исходящему весу + принудительно DNg13 L/R (11074/512006), DNp01 L/R (10001/10010), DNp09, MDN, DNa01/02, DNp20, DNpe017 — все 18 присутствуют.

## Динамика (константы Fly Dino v2)
```
W[j,i] = c·s[j] / Σ|c·s| (нормировка в постсинапс); ACh +1; GABA/Glu/hist −1; DA/5HT/OA +1; unclear → predicted → 0
h ← 0.3·h + 0.7·tanh(u + 1.4·W·h)   ×3 итерации;  выход = 4·h[DN]
```
Реализация: scipy.sparse CSR (граф заморожен, autograd не нужен; torch CPU sparse-CSR matmul был в 37× медленнее).

## Обучение
PPO (собственный компактный, torch): 1 env × 128 шагов × 400 updates = 51 200 решений, lr 3e-4, 4 эпохи, mb 64, clip 0.2, ent 0.02, γ 0.99, GAE λ 0.95, grad-norm 0.5. Readout: actor MLP 82→64(tanh)→61, critic 82→64→1, init seed 20260914.

## Контроли (обязательный набор, FLY_BRAIN_REFERENCE §6)
| Условие | Что доказывает |
|---|---|
| fly (trained) | основной результат |
| fly-silenced | зависимость от активности схемы (тот же readout, DN=0) |
| fly-untrained | факт обучения (тот же init) |
| mlp (тот же бюджет на raw obs) | что даёт именно коннектом (урок FLYT3: 85.7 vs 60.8) |
| random | нижняя граница |
| openloop (forward/attack) | шорткат-контроль (урок fly-craftax: их PPO был «часами с джиттером») |

Все rollout'ы экспортируются в `outputs/benchmark.json` (per-episode: seed, steps, reward, level, xp, kills, deaths, quests) — **наши доказательства это они, а не чужие результаты**.

## I/O sanity (пройден до обучения, check_io.py)
- DN активны: active fraction 1.000, mean|act| ≈ 0.046
- obs驱动: full-vs-black Δ ≈ 0.016–0.027 > 0
- silencing: ровно 0

## Результаты

### Фаза 1: дефолтные награды сервера (seed 20260914, 400 updates × 128 шагов, 745 с)
Кривая обучения (mean эпизодного return по чанкам updates): **−10.47 → −3.21 → −1.41 → +0.78 → +2.52** — обучение есть: сначала.policy гибла (death −5), к концу выживала полный эпизод с положительным return.

Held-out бенчмарк (сиды 900001–900005, `outputs/benchmark_default-rewards.json`):

| Условие | Mean reward | Смерти (5 эпизодов) |
|---|---:|---:|
| fly (trained) | **0.000** | **0** |
| fly-silenced | 0.000 | 0 |
| fly-untrained | 0.000 | 0 |
| random | −1.28 | 2 |
| openloop (forward/attack) | −71.5 | 71 |

Интерпретация (честно): обученная муха **перестала умирать** (random гибнет в 2/5, openloop — до 67 раз за эпизод), но нашла локальный оптимум «стой в безопасности» — reward ровно 0, и контроли (silenced/untrained) тоже стоят на месте, поэтому на дефолтных наградах они неразличимы. Дефолтная награда делает пассивность выгодной: engagement рискован (death −5), а простой не наказуем.

### Фаза 2 (v2): engagement-награды — ОБЪЯВЛЕНА ДО ЗАПУСКА
Чтобы муха именно **играла**, простой сделан убыточным, а бой — выгодным (конфиг объявлен до обучения, сиды 20260915):
```json
{"xp": 0.02, "kill": 1.0, "timePenalty": 0.001, "questProgress": 1.0, "questDone": 10}
```
(death −5 и damage ± без изменений; idle 1200 шагов = −1.2). Бюджеты: fly и mlp-control по 600 updates × 128 шагов, один и тот же seed-поток.

Кривая обучения fly v2 (64 эпизода, mean return по чанкам): **−1.10 → +5.07 → +7.52 → +19.73** (пик 25.4); устойчивые поздние эпизоды ≈ +23 = квесты/xp/киллы минус time-penalty.

**Held-out бенчмарк v2** (сиды 900001–900005, `outputs/benchmark_v2.json`, per-step трейсы внутри):

| Условие | Mean reward | Квесты | Смерти |
|---|---:|---:|---:|
| **fly-sampled (обученная муха, сэмплирование)** | **+19.27** | **4/5** | **0** |
| fly-sampled-silenced (тот же readout, схема=0) | 1.20 | 0 | 0 |
| fly-sampled-untrained (тот же init) | 1.20 | 0 | 0 |
| mlp-sampled (raw obs, тот же бюджет) | 1.45 | 0 | 0 |
| fly / mlp / silenced / untrained (greedy argmax) | 1.20 | 0 | 0 |
| random | −4.48 | 0 | 6 |
| openloop | −69.27 | 0 | 70 |

Выводы (строго по нашим rollout'ам):
1. **Муха играет**: 4 из 5 held-out эпизодов — завершённый квест, 0 смертей, +23 очка; трейс показывает target_nearest/attack/interact/способности/повороты (mix: turn_left 38, target_nearest 17, attack 11, interact 10 на последние 400 событий).
2. **Поведение зависит от коннектома**: silenced-схема с теми же весами readout теряет квесты полностью (1.20).
3. **Поведение зависит от обучения**: untrained — 1.20.
4. **MLP-контроль на тех же бюджетах квесты не нашёл** (1.45). Оговорка: один seed, один бюджет — это не доказательство превосходства топологии, а отсутствие альтернативного объяснения в рамках этого эксперимента.
5. **Greedy argmax вырождается в пассив** (1.20 у всех) — оценивать надо стохастическую политику, как в fly-craftax M4.

Известные ограничения v2: один training seed (нужны реплики); 76 800 решений — маленький бюджет для PPO; квесты — стартовая зона, level-up не достигнут; greedy-режим не обучен; circuit subset 8 835 клеток; traced-only edges.

## Запуск
```sh
# окружение (в клоне levy-street/world-of-claudecraft):
npm install esbuild && npx esbuild headless/env_server.ts --bundle --platform=node --format=cjs --outfile=dist-env/env_server.cjs
# схема:
python3 build_circuit.py /path/to/malecns data
# проверка I/O:
python3 check_io.py
# обучение + авто-бенчмарк:
python3 train.py --policy fly --updates 400 --steps 128 --envs 1
python3 train.py --policy mlp --updates 400 --steps 128 --envs 1
python3 train.py --eval-only --eval-episodes 5
```

При `--envs > 1` сервер окружения может умереть; базовый `wow_env.py` глотает его stderr
(`stderr=subprocess.DEVNULL`), поэтому наружу вылезает только `OSError: [Errno 22]`.
`env_robust.py` это чинит — причина видна, сервер перезапускается, прогон доживает до конца
(`ENV_ROBUST.md`, лог краш-теста `../reference/env_crash_test_log.json`).

## Прогресс: играет ли муха (а не «какой reward»)

Reward набирается и стоя на месте (`questProgress` капает), поэтому прогресс измеряется
отдельно — `progress_eval.py` (`../OFFLINE_PLAY.md` — офлайн-ранбук и дорожная карта):

```bash
WOC_PYTHON_PATH=/path/to/world-of-claudecraft/python python3 progress_eval.py \
  --policy fly-sampled --episodes 3 --max-steps 8000
```

Замер на закоммиченных весах, полный эпизод сервера (8000 шагов = 33 игровых минуты):

| Условие | reward | уровень | xp | киллы | смерти | квесты |
|---|---:|---:|---:|---:|---:|---:|
| fly-sampled | 39.47 / 38.76 / 39.32 | 1 | 60 | 0 | 0 | 1 |
| fly (greedy) | 8.00 | 1 | 0 | 0 | 0 | 0 |

Первый квест закрывается на шаге ~724, дальше эпизод не даёт прогресса: уровень 1 в конце,
как и в начале. 71.6 % шагов — касты способностей (ресурс «один каст за GCD»).

Что добавлено, чтобы это исправить:

- `FLY_FEATURES=v2` — навигационный энкодер (`extract_features_v2` в `fly_brain.py`): те же
  13 каналов и тот же `circuit.json`, но вместо средних — пеленги мобов, близость
  интерактива и «есть что сдавать» по квестам. Требует переобучения readout.
- `--mask-abilities` — маскирует способности, пока тикает GCD; согласовано в роллауте и в
  PPO-апдейте. Обучение и оценка — с одним и тем же флагом.

## Оракул квестов и шейпинг награды (M3)

Замер полного эпизода (8000 шагов) с v2-энкодером, маской GCD и γ0.999: политика
делает 2–4 килла и **0 квестов**. Причина измерима: obs показывает цель только в
радиусе 1.5×40 = 60 юнитов, а первый квестовый NPC стоит в **~756 юнитах** от точки
спавна — сигнала туда нет вообще, квестовая цепочка недостижима.

`quest_oracle.py` + `data/quest_oracle.json` (генерится из самого игрового
`src/sim/quest_targets.ts`, см. `tools/dump_quest_oracle.ts`): 224 квеста в порядке
obs, 215/252 целей с мировыми координатами, у каждого квеста — позиции выдающего и
принимающего NPC, 153 квеста связаны `requiresQuest`.

```bash
python3 quest_oracle.py --table    # сводка таблицы
python3 quest_oracle.py --check    # сверка с живым симом: слоты obs, координаты
```

Обучение с наградой за сокращение дистанции до следующей цели:

```bash
FLY_FEATURES=v2 python3 train.py --policy fly --mask-abilities --oracle-shaping 0.15 \
  --gamma 0.999 --steps 256 --max-steps 8000 --updates 600 --envs 2 --tag m3o --ckpt-every 25
```

Боковой канал в политику (то, что закрывает разрыв «шейпинг без признака»):
`--oracle-obs` добавляет те же 5 чисел прямо в readout (+5 входов), не трогая
замороженную схему. Шейпинг даёт градиент, но не говорит, куда идти; канал даёт
направление. Замер политики с ним — тем же флагом в `progress_eval.py`.

Флаги обучения, добавленные под длинные квестовые цепочки: `--gamma` (0.99 → 0.999),
`--lam`, `--ckpt-every N` (чекпойнт и лог каждые N апдейтов — переживает перезапуск
песочницы), печать `[ep]` по факту закрытия эпизода.

## Раскладка obs: выводится из окружения, а не зашита

Игра считает вектор как `obsSize() = 60 + 2*ABILITY_SLOTS + 2*QUEST_ORDER.length`
(+3, если в версии уже есть хвост паладина, `src/sim/obs.ts`). Обе переменные
меняются от версии к версии, поэтому любой зашитый индекс после блока
способностей рано или поздно читает чужие поля. Замеры сняты **исполнением
игрового кода** (`tools/probe_game_shape.ts`), а не регексом:

| Версия игры | obs | действий | способностей | квестов | формула |
|---|---:|---:|---:|---:|---|
| v0.30.0–v0.31.0 | 344 | 59 | 46 | 96 | 60 + 92 + 192 |
| v0.32.0–v0.35.0 | 556 | 59 | 46 | 202 | 60 + 92 + 404 |
| v0.36.0–v0.39.0 | **567** | 61 | 48 | **204** | 63 + 96 + 408 |
| v0.40.0 | 587 | 61 | 48 | 214 | 63 + 96 + 428 |
| v0.41.0 | 593 | 61 | 48 | 217 | 63 + 96 + 434 |
| v0.42.2 / main | 607 | 61 | 48 | 224 | 63 + 96 + 448 |

Отсюда важное: **одна длина obs не определяет раскладку**. 567 дают и
(48 способностей, 204 квеста) — это реальная v0.36–v0.39.0, — и гипотетические
(28, 224). Поэтому `obs_layout.py` требует второе число из окружения
(число действий = 13 + способности) и сверяет с ним таблицу квестов.

Что было сломано на сборке v0.36–v0.39.0 (воспроизведено на реальной v0.39.0):
`quest_slots` падал `IndexError: index 602 is out of bounds for axis 0 with size
567`, а v2-энкодер — `ValueError: cannot reshape array of size 411 into shape
(2)`; «интерактивный» блок прочитался бы из полей квестов.

```bash
python3 obs_layout.py              # таблица версий + разбор ошибок
python3 tools/test_obs_layout.py   # все сборки из таблицы разом
python3 quest_oracle.py --check    # раскладка из твоей сборки + сверка таблицы
```

### Таблица оракула привязана к версии

В таблице `data/quest_oracle.json` 224 квеста (main/v0.42.x); для v0.36–v0.39.0
в репозитории лежит `data/quest_oracle_204.json`. Если версия другая, таблицу
надо перегенерировать из своего чекаута игры:

```bash
cd путь/к/world-of-claudecraft
npx --yes esbuild tools/dump_quest_oracle.ts --bundle --platform=node \
    --format=cjs --outfile=/tmp/dump.cjs && node /tmp/dump.cjs > data/quest_oracle.json
# или указать готовую: WOC_QUEST_TABLE=data/quest_oracle_204.json
```

`quest_oracle.py --check` сверит числа и скажет прямо, если таблица не от этой
сборки. Молча «съехавшее» чтение исключено тестом.

Важное следствие: **веса привязаны к числу действий**. Чекпойнт с 61 действием
(`n_actions` внутри файла) не загрузится в сборку с 41: на другой версии обучение
повторяют. Все опубликованные числа (23.688, 39.47, уровни) измерены на сборке
с obs 607 — рядом с ними указывать версию обязательно.

## Границы и честность
- **Circuit subset**: 8 835 из 211 577 клеток. Полный граф — тем же кодом на машине с GPU/большой RAM (W_T строится из любого circuit.json).
- Traced-only edges: часть входов фоторецепторов/LC потеряна; это ограничение датасета, задокументировано.
- Динамика leaky-tanh — упрощение (не LIF Shiu); для LIF-режима нужен порт brain.py из fly-craftax (MIT) с Brian2-оракулом.
- Превосходство биологической топологии НЕ заявляется: для этого нужны matched rewired/MLP-контроли с тем же бюджетом (mlp-контроль здесь есть; rewired — TODO).
- Один training seed — маленькая выборка; для заявления о робастности нужны реплики (≥3 сида, как у Fly Dino).
- Данные MaleCNS: CC BY 4.0 (FlyEM/HHMI Janelia, Cambridge, MRC LMB, Google Research). См. `../fly-reference/THIRD_PARTY_NOTICES.template.md`.
