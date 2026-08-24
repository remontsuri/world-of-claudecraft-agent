# PPO Fine-tune Prep + Parity Audit (2026-08-13)

## Цель (по плану юзера)
Доказать, что BC-B1 можно импортировать в SB3 PPO БЕЗ потери поведения,
перед дорогим PPO-прогоном. Read-only-safe: inspect + parity + (опц.) smoke.

## ЧТО СДЕЛАНО
- train_ppo_from_b1.py: строит SB3 PPO(MlpPolicy, net_arch=[512,256,128],
  Discrete(61)), загружает bc_nav_B1.pt, инспектирует ТОЧНЫЕ state_dict
  (BC и SB3), маппит веса ТОЛЬКО при shape-совпадении, затем PARITY TEST
  (1000 детерминированных состояний: argmax match / logit-err / KL).
- diag_parity.py: диагностика цепочки SB3 forward.

## РЕЗУЛЬТАТ — ПАРИТЕТ FAIL (СТОП)
argmax_match_rate = 75.3%   (цель >=99%)
mean abs logit err = 23.84
max  abs logit err = 36.15
PASS: False -> PPO НЕ запущен (по плану юзера).

## КОРНЕВАЯ ПРИЧИНА (найдена диагностикой)
BC-B1 обучен на 568-dim (567 raw + in_combat_range hysteresis-признак).
SB3 MlpPolicy строит входной слой из observation_space.shape:
  - при WrapperEnv(568): policy_net.0 = (512, 568)
  - при прямом CurriculumEnv(567): policy_net.0 = (512, 567)
Прямой маппинг первого слоя (512,568) -> (512,567) невозможен.
75% argmax = артефакт неполного совпадения слоёв (веса сели, но входная
размерность рассинхронизирована -> logits уезжают).

## ВАРИАНТЫ РЕШЕНИЯ (НЕ ПРИНЯТЫ ВСЛЕПУЮ)
(а) WrapperEnv(568) + убедиться, что SB3 build берёт 568 из obs_space
    (не менять Sim/obs.ts; только Python-обёртка добавляет тот же признак,
    что B1 уже использовал). Самый честный путь к "старту из рабочего B1".
(б) Переобучить BC-B1 на 567 (без in_combat_range) -> совместимо с SB3,
    НО теряем рабочий latch (вариант A из ablation = 1/10, провал).

## СТАТУС
PPO fine-tune ЗАБЛОКИРОВАН паритет-аудитом. Ждать OK юзера на вариант (а).
Долгие PPO-прогоны НЕ запускались.

## Как воспроизвести
therock-test/Scripts/python.exe train_ppo_from_b1.py --parity
therock-test/Scripts/python.exe diag_parity.py

NOTE: BC-only / parity-only. PPO НЕ тестировался (parity failed).
