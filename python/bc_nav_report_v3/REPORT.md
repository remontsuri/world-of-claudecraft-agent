# B1 Freeze + STEP1/2 Audit (2026-08-13)

## Что сделано (по плану юзера)
1. Read-only audit DAgger-реализации (bc_nav_dagger.py).
2. STEP 1: B1 closed-loop на 30 FRESH seeds (66-95), вне train/agg.
3. STEP 2: B1 vs Oracle trajectory audit (seeds 66-70).

NO training, NO DAgger, NO PPO. Только eval + audit.

## AUDIT bc_nav_dagger.py
- ЛОГИКА КОРРЕКТНА: BC действует в env (env.step(bc_act)), Oracle метит ТОТ ЖЕ
  obs, что видел BC. Covariate-shift fix честный.
- БАГ: feature-skew in_combat_range. Train пересчитывает _row_feats с жёстким
  dist<=6.0, а inference использует CombatRangeTracker hysteresis (enter<=5,
  exit>7). Новые DAgger-строки рассинхронизированы с inference.
- СТАТУС: DAgger НЕ запускался (юзер: сначала audit + STEP1/2). Баг чинить ТОЛЬКО
  если DAgger понадобится позже.

## STEP 1: B1 на 30 fresh seeds (66-95)
episodes_with_kill = 27/30 (90%)
death_rate         = 10%  (3/30)
mean damage        = 65
atk%<5yd           = 79.7
mean target_sw     = 2.2
time_to_dmg        = 104 steps
time_to_kill       = 156 steps
mean combat_steps  = 263
mean combat_exits  = 0.6
mean max_loop      = 49

GATE (юзер: eWkill>=24/30 AND death<=20%): PASS (27/30, 10%).

## STEP 2: B1 vs Oracle trajectory audit (seeds 66-70)
- Расхождения ТОЛЬКО в NAV/ACQUIRE: target_nearest<->forward микро-болтовня.
- COMBAT: B1 == Oracle (attack = attack, 15+ шагов подряд).
- Covariate shift НЕ проявляется: B1 стабильно доходит до боя и держит режим.

## ВЕРДИКТ
B1 >= 80% kill (90%) -> STOP IL.
B1 = working navigation/combat policy.
DAgger НЕ нужен (covariate shift на fresh seeds не воспроизводится).
Переход к PPO fine-tune ТОЛЬКО после OK юзера.
Прежний DAgger-прогон (B1=13/20) был невалиден из-за бага skew;
истинный B1 = 27/30 чистого closed-loop eval.

## Как воспроизвести
therock-test/Scripts/python.exe oracle_nav_dataset.py
therock-test/Scripts/python.exe bc_nav_ablation.py --only B1 --skip-train
therock-test/Scripts/python.exe bc_nav_b1_audit.py

NOTE: BC-only audit. PPO НЕ тестировался.
