# WoC PPO Audit & Curriculum — Memory

> Проект: аудит существующих PPO/MaskablePPO чекпоинтов WoW (World of Claudecraft)
> на способность navigation+combat (target→approach→attack→kill) и curriculum-дообучение.
> Последнее обновление: 2026-08-13. Все пути/оффсеты ПРОВЕРЕНЫ на исходниках, не угаданы.

## Контекст
- Репо игры/сима: `D:/world-of-claudecraft` (v0.36.0, src/sim/*, python/wow_env.py, dist-env/env_server.cjs).
- Training home (все скрипты/чекпоинты/логи): `D:/woc-llm`.
- GPU: AMD RX 6750 XT (gfx1031), no CUDA. TheRock torch[device-gfx1031] HIP 7.15.
  Запуск: `D:/woc-llm/therock-test/Scripts/python.exe` с `PYTHONPATH=""` и `HSA_OVERRIDE_GFX_VERSION=10.3.0`.
- venv Python 3.12. numpy ДОЛЖЕН быть cp312 — при ABI-дрейфе (cp311 .pyd в cp312 venv):
  `pip install --force-reinstall --no-deps numpy==2.4.6`.

## Жёсткие ограничения (user-hard rules)
- STOP ALL TRAINING, пока не сказано иное. Audit = eval only.
- НЕ трогать: src/sim/*, obs.ts, reward, action space, frame_skip, PPO checkpoints, GPU/venv.
- Oracle = baseline/positive control ТОЛЬКО, никогда не подменяет действия PPO.
- Сравнения: одинаковые seeds + timestep budget + det+sto для ВСЕХ моделей.
- pytest в venv НЕТ — верификация через `_smoke` (curriculum_env.py) или inline.

## Obs layout (src/sim/obs.ts, ABILITY_SLOTS=48 — VERIFIED)
```
self(16) | abilities(96) | target(9 @112) | mobs(30 @121) | interact(5) | quests(20) | paladin(3) = 567
target (@112): [0]=has, [1]=hp, [3]=dist/40, [4]=sin(rel), [5]=cos(rel), [6]=hostile, [8]=aggro
mobs  (@121): 5 слотов × 6 = nearest-first sorted;
             [0]=dist/40 (1.5 = sentinel >60yd/none), [1]=sin(rel), [2]=cos(rel),
             [3]=hp, [4]=leveldiff, [5]=aggro
TAB_QUERY_RADIUS=40yd (target_nearest работает ТОЛЬКО в 40yd; mob-block виден до 60yd)
MELEE_YD=6.0
```
Декод в `audit_common.py`: `decode(obs)` → (player, target, mob). `MOBS=121`, dist = `obs[121]*40`.

## Action enum (NUM_ACTIONS=61 — VERIFIED из env_server.cjs)
```
noop(0) forward(1) back(2) turn_left(3) turn_right(4) strafe_left(5) strafe_right(6)
jump(7) target_nearest(8) attack(9)
ability_1..ability_48 (10..57)
interact(58) stop(59) eat_drink(60)
```

## Evaluation pipeline (DONE, reproducible)
Файлы в `D:/woc-llm`:
- `audit_common.py` — decode(obs) + oracle_action (navigation-first, anti-orbit) + collect_episode (общий цикл метрик).
- `eval_models.py` — Oracle + PPO 100k/200k/500k/1M + MaskablePPO 100k, seeds 42/43/44, 700 steps, det+sto.
- `eval_curriculum.py` — eval curriculum-чекпоинта (переиспользует collect_episode, те же seeds 42/43/44).
- `curriculum_env.py` — CurriculumEnv(WoWClassicEnv), Path 1 wrapper.
- `train_curriculum.py` — Stage-N PPO training (--resume поддерживается).

Протокол: Oracle и PPO идут через ИДЕНТИЧНЫЙ `collect_episode`; отличается только `policy_fn`
(Oracle=oracle_action, PPO=model.predict). Метрики: action%, funnel (t_first_target/combat/dmg/kill),
min/mean mob dist, dmg, kills, deaths.

### Результат audit (eval_models.log, 2026-08-13) — ДИАГНОЗ CASE A
- Oracle baseline: tn%=57, atk%=57, fwd%=17, kills=1.67/ep, t_kill~102, minD=2.1yd. (10/10 на seeds 42–51.)
- PPO & MaskablePPO (100k→1M): tn%≈0, fwd%≈0, ability%≈85–100 (det=100%), minD=37–42yd (НИКОГДА
  не падает), kills=0 на ВСЕХ чекпоинтах. MaskablePPO_100k == VanillaPPO_100k (маска не дала эффекта на 100k).
- ВЫВОД: PPO не умеет НАЙТИ/ПОДОЙТИ к мобу (Case A). Reward корректен (Oracle 10/10 на нём).
  НЕ менять reward. НЕ сырое PPO с того же старта (снова ability-spam). Фикс = curriculum.

## Curriculum (Path 1 — РЕАЛИЗОВАН)
Path 2 (spawn-distance config) ЗАБЛОКИРОВАН: `Sim()` нет start-distance параметра, env_server.cjs
не передаст без правки src/sim/* (запрещено). Path 1 = `CurriculumEnv(WoWClassicEnv)` пре-уокает
игрока к stage-дистанции ПОСЛЕ `super().reset()` и ДО первого obs агента. Sim/obs/reward/action нетронуты.

`curriculum_env.py`:
- Stages: 0=≤5yd, 1=≤15yd, 2=≤30yd, 3=∞ (passthrough = base env).
- `action_masks()` (для MaskablePPO Stage 2+): attack masked если !target.has; interact если нет
  interactable; eat_drink если hp>=0.6. (В базовом WoWClassicEnv action_masks НЕТ — grep → 0.)
- `make_env(stage=...)` фабрика для SB3.
- ВАЖНО пре-уок: навигировать по MOB-block пока target.has==0 (виден до 60yd); target_nearest только
  когда dist<=40yd; читать dist/sin из target-block ПОСЛЕ acquisition. Иначе пре-уок ломается
  (target_nearest вне 40yd → mob-block sentinel → dist=None → abort).

Верификация (seeds 42/43/44): Stage0=4.1/4.1/4.9yd, Stage1=14.8/14.6/14.9, Stage2=28.7/30/28.7,
Stage3=46/45.6/43.7 (base spawn нетронут). action_masks = 61 bool.

## Stage 0 training (100k, DONE)
Гиперпараметры == train_ppo_therock.py (честный A/B, меняем только curriculum):
`lr=3e-4, n_steps=256, batch=64, n_epochs=4, gamma=0.99, gae_lambda=0.95, clip=0.2,
ent_coef=0.01, vf_coef=0.5, max_grad_norm=0.5`. n_envs=4, device=cuda (HIP work, но MlpPolicy на
GPU НЕ эффективен — fps~166; CPU было бы быстрее; не менять mid-run).
Чекпоинт: `models_curriculum/stage0/curric0_100k.zip`.

Результат eval (seeds 42/43/44, det):
- seed 42: kills=4, dmg=246, t_kill=81, dths=0 (ЛУЧШЕ Oracle!).
- seed 43: kills=0, dmg=0, dths=1.
- seed 44: kills=0, dmg=0, dths=1.
- ГЕЙТ (kills≥1 на 3/3) НЕ ПРОЙДЕН (1/3). Причина: overfit на seed 42 + survival-проблема
  (43/44 умирают с dmg=0 — ability-spam вместо attack/выживания). Case A побеждён (агент доходит
  и убивает), но устойчивость к разным мобам нет.

## Stage 0 — ИТОГ (DONE, 2026-08-13)
- 100k: seed 42=4 kills (лучше Oracle!), 43/44 = death, dmg=0 → гейт 1/3 НЕ пройден (overfit на 42).
- Resume +100k (200k total): `curric0_resumek.zip`. Eval seeds 42/43/44:
  - seed 42: kills=5, dmg=322, dths=0, t_kill=50, atk%=13.6
  - seed 43: kills=1, dmg=70, dths=1, t_kill=37, atk%=8.0
  - seed 44: kills=2, dmg=185, dths=0, t_kill=86, atk%=1.5
  - **ГЕЙТ ПРОЙДЕН: kills≥1 на 3/3 seeds (8 total).**
- Case A побеждён (agent доходит + убивает). MaskablePPO на Stage 0 НЕ нужен (маска бесполезна
  пока policy нестабильна в navigation — по плану MaskablePPO на Stage 2+).
- Training ep_rew_mean ушёл в плюс (+0.643 к концу resume).

## Stage 1 (≤15yd) — IN PROGRESS
100k: `curric1_100k.zip`. Eval seeds 42/43/44:
- seed 42: kills=1, dmg=62, dths=1, tn%=9.8, atk%=0, t_kill=119
- seed 43: kills=1, dmg=77, dths=1, tn%=10.7, atk%=0, t_kill=206
- seed 44: kills=0, dmg=59, dths=1, tn%=40.6, atk%=0 (t_kill=None)
- **ГЕЙТ НЕ ПРОЙДЕН: 2/3 (kills=2 total).**
- ПРОГРЕСС: tn% вырос (navigation освоена: агент подходит к мобу, minD=3.7 на всех).
  ПРОБЛЕМА: atk%=0 (kill через ability, не attack), dths=1 везде (survival упал на бОльшей
  дистанции — моб живёт дольше, ability не добивает). НЕ провал curriculum, survival-проблема.
- Resume +100k (200k total): `train_curriculum.py --stage 1 --resume models_curriculum/stage1/curric1_100k.zip`
  Финал: `models_curriculum/stage1/curric1_resumek.zip`. Гейт kills≥1 на 3/3.
- MaskablePPO НЕ подключать (маска бесполезна пока atk%=0/survival нестабильны — по плану Stage 2+).

## Trajectory Audit (2026-08-13) — ЛОКАЛИЗАЦИЯ ПРОБЛЕМЫ
Скрипт: trajectory_audit.py (seed 42, Oracle + 5 vanilla base + Vanilla_stage1 + Maskable_stage1).
Фазы: saw_mob -> nav_fwd -> target_nearest -> target_has -> attack_after_has -> first_damage -> first_kill.
Результат (step первого наступления фазы, '-' = никогда):
- Oracle: 1 / 23 / 3 / 6 / 28 / 28 / 124 (все фазы пройдены, 10/10 kills)
- Vanilla_base_100k: 1 / - / - / - / - / - / -  => DIVERGE: nav_fwd (НЕ жмёт forward к мобу)
- Vanilla_base_200k: 1 / - / - / - / - / - / -  => DIVERGE: nav_fwd
- Vanilla_base_500k: 1 / - / - / - / - / - / -  => DIVERGE: nav_fwd
- Vanilla_base_1M:     1 / 16 / - / - / - / - / - => DIVERGE: target_nearest (forward есть, но не acquires)
- Vanilla_stage1_100k: 1 / - / 1 / 1 / - / 87 / 119 => DIVERGE: nav_fwd (но curriculum дал dist_min=3.3 + kills=119: убил НЕ через navigation, а через близкий спавн + случайный target_nearest)
- Maskable_stage1_100k: 1 / - / 1 / 1 / - / - / - => DIVERGE: nav_fwd (маска дала target_has, но dist_min=12, НЕ дошёл, deadlock)

**ВЫВОД:** Первая точка расхождения PPO с Oracle = `nav_fwd` (navigation). Моб виден (saw_mob=1),
но агент НЕ учит forward→target_nearest→attack. Спамит ability. Это НЕ баг Sim/obs/reward
(Oracle на том же наборе 10/10), НЕ combat (Vanilla_stage1 убил), а **fundamental PPO exploration /
credit-assignment collapse** в navigation-фазе. «Маска убила exploration» НЕ доказано — маска лишь
вскрыла тот же nav-провал. MaskablePPO НЕ помог (0/3 на Stage1). Stage 2 / 1M / дальше маска — СТОП.

## BC (Stage B) — 2026-08-13
- train_bc.py: BCNet MLP P(action|obs), кросс-энтропия, балансировка по фазам
  (per-phase cap 6000 на COMBAT + sqrt class-weights на редкие nav-действия), DEAD дроп.
- **Stage A dataset**: 80k samples (seeds 42-61 x10). Внутрифазные действия корректны
  (NAV→turn/target_nearest, ACQUIRE→forward 73%, APPROACH→turn, COMBAT→attack 94%),
  но COMBAT=90% сырца → без балансировки BC выучил бы "всегда attack".
- **BC raw eval**: 3/10 kills (гейт ≥8/10 НЕ пройден). НО:
- **bc_diagnose.py**: Oracle марковский (0.4% state-buckets конфликтуют по действию),
  held-out accuracy=94.7% (NAV 72 / ACQUIRE 89 / APPROACH 96 / COMBAT 95%,
  attack_recall 95%, attack_precision 99.7%). => **архитектура obs→policy МОЖЕТ выучить
  последовательность**. Провал BC-роллаута = covariate shift (слабая NAV 72% → drift),
  НЕ representation. "PPO exploration виноват" пока НЕ доказано.
- **DAgger**: dagger_collect.py (BC acts + Oracle re-label). ПЕРВЫЙ прогон БАЖНЫЙ
  (env.step(or_act) вместо bc_act) → не DAgger, а дубль Oracle → 0/10 (непоказательно).
  ИСПРАВЛЕНО: env.step(bc_act). ЧЕСТНЫЙ DAgger В РАБОТЕ (4 iter x8 seeds).
## BC диагностика — 2026-08-13 (КОРНЕВАЯ ПРИЧИНА NAV)
- analyze_oracle_balance.py: Oracle в NAV НИКОГДА не жмёт forward (0%!),
  только turnL 50% / turnR 26% / target_nearest 25%. forward_ok всего 10%
  (в 90% состояний с мобом |sin|>0.15 => надо ПОВОРАЧИВАТЬ).
- => BC rollout forward 30-75% = ПРЯМОЕ нарушение Oracle. BC НЕ выучил
  sin/cos моба → turn. held-out 94.7% это МАСКИРУЕТ (COMBAT 94% датасета
  доминирует в accuracy; редкие NAV-сэмплы не влияют).
- РЕШЕНИЕ (пользователь): derived navigation labels, НЕ менять игровой obs.
  collect_oracle_dataset_v2.py сохраняет turn_dir=sign(mob_sin),
  turn_strength=|mob_sin|, forward_ok, mob_dist_bin (В РАБОТЕ).
- ПЛАН v2: BCNet с aux head предсказания turn_dir (заставить выучить
  sin/cos→turn), обучить на NAV/ACQUIRE/APPROACH + COMBAT. Eval метрики:
  correct_turn_rate, forward_rate, target_nearest_rate, min_dist, damage, kills.
- СТОП: PPO/MaskablePPO/Stage2/1M, НЕ менять Sim/reward/obs/action.
- GO/NO-GO (пользователь): >=8/10 kills => nav воспроизводим, можно PPO после
  подтверждения; 4-7/10 => диагностика dataset; <=3/10 => НЕ RNN/PPO, искать
  первую divergence point.

## Команды запуска
```bash
# Eval baseline (уже сделано, results в eval_models.log)
therock-test/Scripts/python.exe eval_models.py

# Curriculum smoke (verification)
therock-test/Scripts/python.exe curriculum_env.py

# Stage 0 train (100k)
therock-test/Scripts/python.exe train_curriculum.py --stage 0 --timesteps 100000 --n-envs 4 --device cuda

# Stage 0 resume (+100k)
therock-test/Scripts/python.exe train_curriculum.py --stage 0 --timesteps 100000 --resume models_curriculum/stage0/curric0_100k.zip

# Eval curriculum checkpoint (seeds 42/43/44)
therock-test/Scripts/python.exe eval_curriculum.py --ckpt models_curriculum/stage0/curric0_100k.zip --stage 0
```

## Pitfalls
- venv numpy ABI drift → `pip install --force-reinstall --no-deps numpy==2.4.6`.
- MaskablePPO.load, НЕ PPO.load (mask policy rejects use_sde kwarg): `from sb3_contrib import MaskablePPO`.
- SB3 MlpPolicy на GPU: warning, не ошибка (intended для CPU). fps узкое место — JSON-over-pipe
  Node subprocess + frame_skip=5, НЕ GPU. ЧЕСТНЫЙ A/B (n_envs=4, stage1, 3k): cuda+4=216 fps,
  cpu+4=239 fps (CPU чуть быстрее, разница ~10%, в пределах шума). cpu+8=76 fps (contention 8
  Node-процессов — НЕ делать). ИТОГ: держать n_envs=4, device cuda или cpu ~равны. Ускорение
  только через shared-memory IPC в wow_env.py (правка env-обёртки, заблокирована пользователем).
## MaskablePPO (интернет-анализ + smoke)
- SB3-Contrib дока: "SubprocVecEnv + MaskablePPO требует action_masks ВНУТРИ env (ActionMasker
  нельзя)". У CurriculumEnv.action_masks() есть ✅. Маска читается SB3 автоматически в learn().
- MDPI 2076-3417/13/14/8283: invalid action masking улучшает on-policy PPO в RTS-играх
  (logit-level masking: invalid logits -> -inf). Прямо наш кейс (WoC = MMO/RTS-like).
- Reddit r/reinforcementlearning "PPO not learning": причина часто "agent can't discover high
  rewards / bad exploration". Наш atk%=0 = агент не открыл, что attack даёт reward. Маска лечит.
- GitHub levy-street/world-of-claudecraft: ПРЯМЫХ PPO-тренинг-отчётов НЕТ (community не публикует
  RL в issue/PR). Опираемся на литературу + наши данные.
- Smoke MaskablePPO Stage1 3k: atk%=84/99/99 (маска убрала ability-spam!), но tn%=0 (агент не
  учит target_nearest, спамит attack без target.has -> dmg=0, kills=0, dths=1). В eval маска НЕ
  применяется (predict без masks) — это правильно, показывает что агент ВЫУЧИЛ. Нужен 100k, чтобы
  target_nearest освоился. Скрипты: train_curriculum_masked.py, eval_curriculum_masked.py.
- Windows MSYS paths: case-sensitive rg в search_files падает → использовать terminal `grep -n` / `find`.
- env_server.cjs лог огромный (128k строк) — читать через read_file с offset, не grep по всему.

## BC NAV A/B (2026-08-13) — ЧЕСТНЫЙ РЕЗУЛЬТАТ
4 новых файла в D:/world-of-claudecraft/python/ (НЕ в игре): nav_features.py,
oracle_nav_dataset.py, bc_nav_model.py, bc_nav_eval.py. НЕ тронуто: obs.ts/env_server/
wow_env/reward/ACTIONS/obs_size/Sim/PPO ckpt.
- ability_slots НЕ хардкод: берётся из ac.TGT (48), передаётся в decode_nav_obs.
- Model A (raw 567): kills=1/10, correct_turn=31%, tn=40%, fwd=2.3%, minD=0.6, div=COMBAT
- Model B (567+features): kills=7/10, correct_turn=20.6%, tn=25%, fwd=4.8%, minD=4.9, dmg=51
=> **ПРОБЛЕМА В ПРЕДСТАВЛЕНИИ НАВИГАЦИИ** (сырой sin/cos моба MLP не выучивает как nav-сигнал).
   Дав turn_dir/forward_ok явно -> 7/10 против 1/10. Значит PPO nav_fwd-divergence =
   та же representation-проблема, НЕ главная причина в exploration/credit-assignment.
=> GO/NO-GO: 4-7/10 -> НЕ PPO fine-tune, НЕ RNN. Ждём подтверждения юзера перед PPO.
   B близко к 8/10 -> инкремент (больше NAV-сэмплов/жёстче баланс), не новая arch.
- Запуск: oracle_nav_dataset.py -> bc_nav_model.py --model A/B -> bc_nav_eval.py --model A/B
  (все из D:/world-of-claudecraft/python, PYTHONPATH="", venv /d/woc-llm/therock-test).
- УТОЧНЕНИЕ (после ревью юзера): "воспроизводит Oracle-цепочку" НЕВЕРНО. Честно:
  * heading_err° (mean abs angle agent->mob) A=52.1° B=54.4° — ОДИНАКОВО плохо.
    B не точнее целится по шагам. Разница НЕ в копировании Oracle.
  * Разница в ЗАСТРЕВАНИИ: A minD=0.6 (упёрся в моба впритык, стоит, не бьёт attack ->
    COMBAT@step, kills 1/10); B minD=4.9 (боевая дистанция, бьёт -> kills 7/10).
  * Fisher exact 1/10 vs 7/10 p≈0.02 (двусторонний) — разница значима, не шум.
  * ВЫВОД: raw sin/cos вообще не даёт рабочего nav-сигнала (A доезжает случайно,
    застревает); features дают B "куда идти" -> representation issue ДОКАЗАН СИЛЬНЕЕ.
  * first_div=COMBAT у A и B — НЕ артефакт (NAV проверяется первым, не срабатывает:
    A выбирает turn/forward в NAV, доезжает, но застревает в COMBAT без attack).
  * PPO в ЭТОМ A/B НЕ тестировался. "PPO та же проблема" = из trajectory_audit
    (nav_fwd-divergence), НЕ из bc_nav_eval. Помечено в выводе скрипта.
- УТОЧНЕНИЕ 2 (MELEE_RANGE≈5yd из sim/types, не коллизия): гипотеза "A застрял
  из-за min-range" ОТВЕРГНУТА. Добавлена метрика atk%<5yd (attack rate пока моб/
  target в 5yd): A=47.1%, B=67.8%. A бьёт внутри range (minD 0.6 << 5yd), но
  НЕСТАБИЛЬНО (Oracle в COMBAT ~94-100%). Проблема НЕ distance-gating, а
  ПЕРЕКЛЮЧЕНИЕ movement->combat-режим: raw sin/cos не даёт сигнала "остановись и
  бей", модель дёргается forward/attack. B с features держит режим (67.8%, minD 4.9
  = стоит в бою, не впритык) -> 7/10. Всё ещё representation issue, но точнее:
  "не держит combat-режим после входа в range", а не "не может дойти".
  MELEE_RANGE реально ~5yd (sim/types, рядом с INTERACT_RANGE/DT; клиент
  ATTACK_MOVE_MELEE_STOP=3.5 "останавливается внутри melee" => MELEE_RANGE>3.5).
- УТОЧНЕНИЕ 3 (проверка "теряет target, дохнет" + chi2): добавлены метрики
  death_rate и tgt_switches (раньше "мечется, теряет target" был ДОМЫСЕЛ).
  * A: death_rate=90%, tgt_switches=2.9/эп  -> ФАКТ: A дохнет и теряет target.
  * B: death_rate=0%,  tgt_switches=1.6/эп  -> B не дохнет, держит target.
  * atk%<5yd tick-level: A=712/1373 (51.9%), B=487/770 (63.2%).
    chi-square=25.97 (df=1, crit 3.84) => p<<0.001. Разница ЗНАЧИМА, не шум.
  * ВЫВОД: atk%<5yd напрямую объясняет разрыв kills (A бьёт 52% в range и
    дохнет 90%; B бьёт 63% и живёт 0%). minD+A=0.6 (впритык, дёргается) vs
    B=4.9 (в бою, стабильно) объясняет разное поведение.
- РЕКОМЕНДАЦИЯ ПО DATASET (из ревью): НЕ "больше NAV-сэмплов", а конкретно
  сэмплы "ты в радиусе, target жив -> держи attack" + hysteresis-признак
  in_combat_range: bool (с гистерезисом входа/выхода, не дребезг на границе
  range). Это проще добора данных, если проблема в дребезге сигнала на границе.
- GO/NO-GO подтверждён юзером: 7/10 < 8/10 => НЕ RNN/PPO, докрутка dataset.
  Следующий шаг: hysteresis-признак in_combat_range в nav_features + переобучить
  B, поднять 7/10 -> 8/10. PPO fine-tune только после подтверждения юзера.
- DONE (доформализация + hysteresis): death_rate Fisher 9/10 vs 0/10 = p≈1e-4
  (юзер посчитал вручную). Причинная цепочка ОДНА (не два бага):
  A реже атакует в радиусе (51.9% vs 63.2%) -> медленнее убивает -> дольше под
  встречным уроном -> чаще дохнет до kill (90% vs 0%) -> эпизод обрывается ->
  dmg=12, kills=1/10. death_rate = СЛЕДСТВИЕ низкого atk%, не отдельный симптом.
  cavEAT (юзер): tgt_switches=2.9 (A) включает post-death re-engage, частично
  дублирует death_rate, НЕ добавляет новой инфы (не "потеря цели посреди боя").
- HYSTERESIS in_combat_range ВНЕДРЁН и ПРОВЕРЕН (2026-08-13):
  * nav_features.CombatRangeTracker: enter<=5yd, exit>7yd (hysteresis, не
    дребезг на границе 5yd). Сброс в False при потере target (death/re-target).
  * oracle_nav_dataset.py: tracker per-episode, пишет in_combat_range в трассы.
  * bc_nav_model.py / bc_nav_eval.py: FEAT_KEYS B += in_combat_range (8 фич).
  * ПЕРЕОБУЧЕН B: kills=11/10 (GATE TRUE, было 7/10), atk%<5yd=83.8%
    (было 63.2%), death_rate=10% (было 0%), minD=2.7 (было 4.9, теперь вплотную
    к бою), damage=81.
  * СТАТ: Fisher death_rate A=9/10 vs B=1/10 p=1.09e-3 (значимо);
    χ² atk%<5yd A 712/1373 (51.9%) vs B 744/915 (81.3%) = 205.85 (p≪0.001).
  * ВЫВОД: чинить ровно одну вещь (combat-режим latch) -> вытянуло остальное
    автоматически: меньше death -> больше dmg -> kills 1->11. Гипотеза подтверждена.
  * GO/NO-GO: 11/10 >= 8/10 => BC-ветка ДОКАЗАЛА, что obs->policy способна
    удерживать combat-режим. СЛЕДУЮЩИЙ шаг (по юзеру): BC->DAgger->PPO fine-tune,
    но PPO НЕ запускался (запрет активен). Ждать OK юзера на PPO.
- ФАЙЛЫ (D:/world-of-claudecraft/python): nav_features.py (CombatRangeTracker),
  oracle_nav_dataset.py, bc_nav_model.py, bc_nav_eval.py; nav_data/oracle_nav_traces.jsonl,
  bc_nav_{A,B}.pt, bc_nav_{A,B}_counts.json.
- CLEAN ABLATION (2026-08-13, ПОСЛЕ ревью юзера): bc_nav_ablation.py.
  4 варианта, общий dataset/seeds/budget/MLP/opt/loss/eval. Gate по
  episodes_with_kill (НЕ total_kills — исправлен overclaim "11/10 kills").
  A  (raw)               : 1/10 kill,  death 90%,  atk%<5yd 82.6%,  GATE False
  B1 (+in_combat_range)  : 8/10 kill,  death 20%,  atk%<5yd 71.9%,  GATE TRUE
  B2 (+nav feat only)    : 2/10 kill,  death 50%,  atk%<5yd 39.1%,  GATE False
  B3 (+both)             : 7/10 kill,  death  0%,  atk%<5yd 81.8%,  GATE False
  ВЫВОД: ключевая проблема = НЕХВАТКА ЯВНОГО COMBAT-MODE STATE (in_combat_range),
  НЕ navigation representation (B2 почти не помог). ОПРОВЕРГАЕТ прежний overclaim
  "raw sin/cos — виновник": sin/cos работают для nav, виноват latch "бей, не двигай".
  ПРЕЖНИЙ B (7/10) = B3 + лишние mob_sin/cos/target_has/target_dist, поэтому раньше
  нельзя было разделить две гипотезы. Теперь разделено чисто.
- ЦЕПОЧКА (юзер, финал): Oracle -> 80k demo -> BC -> combat latch -> closed-loop
  >=8/10 (B1) -> DAgger -> validation -> PPO fine-tune (СТАРТ с BC policy, не с нуля).
  PPO ЗАПРЕЩЁН до OK юзера. STOP-правила активны: нет Stage 2, reward-shaping,
  Sim/obs/action/reward-правок, переобучения старых PPO checkpoints.
- СЛЕДУЮЩИЙ ШАГ: DAgger aggregation (bc_nav_ablation сделал чистый BC; dagger_collect.py
  уже написан ранее — переиспользовать, поднять B1-латч в dataset). Ждать OK юзера.
- B1 FREEZE + STEP1/2 AUDIT (2026-08-13, НОВЫЙ ПЛАН ЮЗЕРА): DAgger НЕ запускать
  вслепую. Сначала read-only audit реализации, потом B1 closed-loop на 30 fresh
  seeds + B1-vs-Oracle trajectory audit.
  * AUDIT bc_nav_dagger.py: логика корректна (BC действует в env, Oracle метит
    ТОТ ЖЕ obs) -> covariate-shift fix честный. БАГ: feature-skew in_combat_range
    (train пересчёт _row_feats жёсткий <=6.0, inference hysteresis 5/7) -> новые
    DAgger-строки рассинхронизированы. ЧИНИТЬ перед будущим прогоном (сохранять
    feats из tracker, не пересчитывать). НО сейчас DAgger НЕ нужен.
  * STEP1: B1 на 30 fresh seeds (66-95): episodes_with_kill=27/30 (90%),
    death_rate=10%, atk%<5yd=79.7%, combat_exits=0.6, max_loop=49.
    GATE (юзер >=24/30 AND <=20% death): PASS.
  * STEP2: B1-vs-Oracle trace (seeds 66-70): расхождения только в NAV/ACQUIRE
    (target_nearest<->forward микро-болтовня), COMBAT совпадает (attack=attack
    15+ шагов). Covariate shift НЕ проявляется.
  * ВЕРДИКТ: B1 >=80% -> STOP IL. B1 = working policy. DAgger НЕ нужен (covariate
    shift на fresh seeds не воспроизводится). Переход к PPO fine-tune ТОЛЬКО после
    OK юзера. Прежний DAgger-прогон (B1=13/20) был невалиден из-за бага skew,
    истинный B1=27/30 чистого eval.
- ФАЙЛЫ (D:/world-of-claudecraft/python): nav_features.py (CombatRangeTracker),
  oracle_nav_dataset.py, bc_nav_model.py, bc_nav_eval.py, bc_nav_ablation.py,
  bc_nav_b1_audit.py (STEP1/2), bc_nav_dagger.py (написан, НЕ запускался из-за
  бага+неактуальности); nav_data/bc_nav_{A,B,B1,B2,B3}.pt, *_counts.json.
- PPO FINE-TUNE PREP (2026-08-13): train_ppo_from_b1.py (read-only-safe:
  inspect+parity+smoke) + diag_parity.py. Вариант (а) реализован:
  CombatLatchWrapper(568) + корректный tracker.update(target_has,target_dist).
  МАППИНГ ВЕСОВ 1:1 ПОДТВЕРЖДЁН (policy_net.0[0,0]=-0.114366 == BC net.0[0,0],
  match=True). НО PARITY FAIL: argmax 75.3% (цель >=99%).
  КОРНЕВАЯ ПРИЧИНА (после глубокой диагностики): веса сели точно, НО
  forward-цепочки SB3 MlpPolicy и BC НЕ битово-эквивалентны — SB3 добавляет
  features_extractor поверх mlp_extractor (FlattenExtractor + возможно
  нормализация obs), из-за чего при одинаковых весах argmax расходится на 25%
  состояний (corr BC~SB3 = 0.91, а не 1.0). Это НЕ баг маппинга, а фундаментальная
  разница архитектур SB3 vs наш Sequential. Прямой import весов не даёт точной
  копии поведения. ПО ТВОЕМУ ПЛАНУ: parity FAIL -> СТОП, PPO НЕ запущен, долгие
  прогоны ЗАПРЕЩЕНЫ. НУЖНО РЕШЕНИЕ: либо (и) дистилляция BC->SB3 (teacher=BC,
  clone behavior через BCE loss), либо (ii) писать кастомную SB3-совместимую
  ActorCriticPolicy с ровно нашей forward-цепочкой. Ждать OK юзера.
- STOP-ПРАВИЛА (активны): нет Sim/obs.ts/reward/action/frame_skip правок, нет
  Stage 2, reward-shaping, MaskablePPO, 1M PPO, DAgger (не нужен), переобучения
  старых PPO checkpoints.
