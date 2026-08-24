# PPO Fine-tune Prep + Parity Audit v5 (2026-08-13)

## Вариант (а) реализован
CombatLatchWrapper(568) + корректный CombatRangeTracker.update(target_has,
target_dist). Не трогает Sim/obs.ts/reward/action — только Python-обёртка.

## РЕЗУЛЬТАТ
МАППИНГ ВЕСОВ 1:1 ПОДТВЕРЖДЁН:
  policy_net.0[0,0] after map = -0.114366
  BC net.0[0,0]            = -0.114366
  match=True
НО PARITY FAIL:
  argmax_match_rate = 75.3%   (цель >=99%)
  mean abs logit err = 27.9
  corr(BC,S,SB3) = 0.91 (а не 1.0)

## КОРНЕВАЯ ПРИЧИНА (глубокая диагностика)
Веса сели ТОЧНО (1:1). Но forward-цепочки SB3 MlpPolicy и нашего BC НЕ
битово-эквивалентны: SB3 добавляет features_extractor (FlattenExtractor)
поверх mlp_extractor, из-за чего при одинаковых весах argmax расходится на 25%
состояний. Это НЕ баг маппинга — это фундаментальная разница архитектур
SB3 (ActorCriticPolicy с features_extractor) против нашего Sequential(ReLU).

## ВЕРДИКТ (по плану юзера)
parity FAIL -> СТОП. PPO НЕ запущен. Долгие прогоны ЗАПРЕЩЕНЫ.

## ВАРИАНТЫ РЕШЕНИЯ (НЕ ПРИНЯТЫ ВСЛЕПУЮ)
(и) Дистилляция BC->SB3: teacher=BC, clone behavior через BCE/KL loss на
    детерминированных состояниях. Не "import weights", а "clone policy".
(ii) Кастомная SB3 ActorCriticPolicy с ровно нашей forward-цепочкой
    (Sequential 568->512->256->128->61 + value head), без features_extractor.

## Статус
PPO fine-tune ЗАБЛОКИРОВАН. Ждать OK юзера на (и) или (ii).

## Как воспроизвести
therock-test/Scripts/python.exe train_ppo_from_b1.py --parity
therock-test/Scripts/python.exe diag_parity.py

NOTE: BC-only / parity-only. PPO НЕ тестировался (parity failed).
