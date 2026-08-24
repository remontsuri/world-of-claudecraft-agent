# BC Navigation Ablation — структура и результаты (2026-08-13)

## Что доказано
- Oracle: рабочая эталонная траектория (10/10 kills, seeds 42-51).
- Dataset: 80 000 transitions, seeds 42-61 × 10 эпизодов (NO training, NO Sim-changes).
- BC способен воспроизвести траекторию при правильном представлении.

## CLEAN ABLATION (главный результат)
4 варианта, ОДИНАКОВЫЙ dataset/seeds(42-51)/budget(40ep)/MLP/optimizer/loss/evaluator.
Derived features считаются ТОЛЬКО в Python (policy/eval), игра НЕ трогается.

| var | feat_keys                        | totKill | eWkill  | death% | atk%<5yd | minD | GATE(>=8/10) |
|-----|----------------------------------|---------|---------|--------|----------|------|--------------|
| A   | [] (raw 567)                     | 1       | 1/10    | 90%    | 82.6%    | 0.7  | False        |
| B1  | +in_combat_range (latch ONLY)    | 8       | 8/10    | 20%    | 71.9%    | 2.3  | TRUE         |
| B2  | +nav feat ONLY (turn_dir/str/fwd)| 2       | 2/10    | 50%    | 39.1%    | 6.2  | False        |
| B3  | +both                            | 7       | 7/10    | 0%     | 81.8%    | 4.7  | False        |

Gate считается по episodes_with_kill (НЕ total_kills). "11/10 kills" исправлен:
пишем episodes_with_kill/X/10 — честно.

## Интерпретация
- B1 >> A (8/10 vs 1/10) -> ключевая проблема = НЕХВАТКА ЯВНОГО COMBAT-MODE STATE.
- B2 ≈ A (2/10) -> navigation representation САМА ПО СЕБЕ почти не помогает.
- B3 = 7/10 (death 0%, atk 81.8% — лучший combat-hold, пара seeds не добила).

ВЫВОД: виновата НЕХВАТКА LATCH'а "остановись и бей" (in_combat_range с
hysteresis), А НЕ representation направления. Это ОПРОВЕРГАЕТ прежний overclaim
"raw sin/cos — виновник": sin/cos работают для навигации, виноват combat-latch.
Прежний B (7/10) = B3 + лишние mob_sin/cos/target_has/target_dist, поэтому раньше
нельзя было разделить гипотезы. Теперь разделено чисто.

## Статус / следующий шаг
Цепочка (юзер): Oracle -> 80k demo -> BC -> combat latch -> closed-loop >=8/10
(B1) -> DAgger -> validation -> PPO fine-tune (СТАРТ С BC policy, не с нуля).
PPO ЗАПРЕЩЁН до OK. STOP-правила: нет Stage 2, reward-shaping, Sim/obs/action/
reward-правок, переобучения старых PPO checkpoints.

## Как воспроизвести
therock-test/Scripts/python.exe oracle_nav_dataset.py
therock-test/Scripts/python.exe bc_nav_ablation.py        # train+eval A/B1/B2/B3
therock-test/Scripts/python.exe bc_nav_ablation.py --only B1 --skip-train  # одиночный

NOTE: BC-only ablation. PPO НЕ тестировался.
