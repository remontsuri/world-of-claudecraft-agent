#!/usr/bin/env bash
# accel_m1_m3.sh — ступени к M1–M3. Каждая следующая запускается только после зелёной
# предыдущей: не тратим сутки счёта, пока не доказано, что сигнал дошёл.
#
#   check — офлайн-проверки (таблицы, раскладка) + сверка таблицы с ЖИВЫМ окружением;
#   smoke — 20 апдейтов: пайплайн живой, чекпойнт пишется (минуты);
#   probe — 300 апдейтов: квестовый сигнал дошёл? (десятки минут)
#   main  — длинный прогон под M1–M3 + приёмка progress_eval.
#
# Запуск (на машине с игрой и GPU):
#   WOC_PYTHON_PATH=D:/woc-game/python bash tools/accel_m1_m3.sh check
#   WOC_PYTHON_PATH=D:/woc-game/python bash tools/accel_m1_m3.sh smoke
#   ... probe, затем main
#
# Ручки: ORACLE_W (вес шейпинга, по умолчанию 0.05 — reward += W * clip(Δdist/40, -1, 1)),
# SEED, TAG, FLY_FEATURES (v2), PROBE_UPDATES, MAIN_UPDATES, MAIN_ENVS, MAIN_STEPS.
set -uo pipefail
cd "$(dirname "$0")/.."

STAGE="${1:?стадия: check | smoke | probe | main}"
W="${ORACLE_W:-0.05}"
SEED="${SEED:-20260917}"
TAG="${TAG:-m1m3}"
PROBE_UPDATES="${PROBE_UPDATES:-300}"
MAIN_UPDATES="${MAIN_UPDATES:-3000}"
MAIN_ENVS="${MAIN_ENVS:-8}"
MAIN_STEPS="${MAIN_STEPS:-256}"
export FLY_FEATURES="${FLY_FEATURES:-v2}"
export WOC_PYTHON_PATH="${WOC_PYTHON_PATH:-}"

# Общие флаги обучения: маска GCD (иначе 70 % шагов — пустые касты), оракул-канал (+5
# входов) и шейпинг по расстоянию до цели. Оценка обязана идти с ТЕМИ ЖЕ флагами,
# иначе замер нечестный (в progress_eval это отдельно оговорено).
TRAIN_COMMON=(--policy fly --seed "$SEED" --max-steps 1200 --no-bench
              --mask-abilities --oracle-obs --oracle-shaping "$W")
EVAL_COMMON=(--mask-abilities --oracle-obs)

fail=0
step() { echo; echo "== $*"; }
need_env() {
  [ -n "$WOC_PYTHON_PATH" ] || { echo "нужен WOC_PYTHON_PATH (python/ игры)"; exit 2; }
  [ -d "$WOC_PYTHON_PATH" ] || { echo "нет каталога: $WOC_PYTHON_PATH"; exit 2; }
}

case "$STAGE" in

check)
  need_env
  step "офлайн-проверки (таблицы оракула, раскладка obs)"
  bash tools/run_checks.sh || fail=1
  step "раскладка obs (самопроверка всех замеренных сборок)"
  python3 obs_layout.py >/dev/null && echo "OK: раскладка" || fail=1
  step "сверка таблицы оракула с ЖИВЫМ окружением"
  python3 quest_oracle.py --check | tail -12 || fail=1
  ;;

smoke)
  need_env
  step "20 апдейтов на 1 окружении: пайплайн, маска, оракул-канал"
  python3 train.py "${TRAIN_COMMON[@]}" --envs 1 --updates 20 --steps 128 --tag smoke || fail=1
  [ -s "outputs/params_fly-smoke.pt" ] && echo "OK: чекпойнт outputs/params_fly-smoke.pt записан" || { echo "ПРОВАЛ: чекпойнта нет"; fail=1; }
  ;;

probe)
  need_env
  step "проверка гипотезы: $PROBE_UPDATES апдейтов, gamma=0.999, шейпинг $W (таг probe)"
  python3 train.py "${TRAIN_COMMON[@]}" --envs 2 --updates "$PROBE_UPDATES" --steps 128 \
      --gamma 0.999 --lam 0.95 --tag probe || fail=1
  step "замер прогресса (1 эпизод, 1200 шагов) — вопрос: квест взяли и пошли?"
  python3 progress_eval.py --policy fly-sampled --checkpoint outputs/params_fly-probe.pt \
      --episodes 1 --max-steps 1200 "${EVAL_COMMON[@]}" \
      --out outputs/progress_probe.json | tail -25
  echo
  echo "смотри: quests_accepted/quests_done > 0 и рост questProgress => сигнал дошёл, идём в main"
  ;;

main)
  need_env
  step "основной прогон: $MAIN_UPDATES апдейтов, $MAIN_ENVS окружений, роллаут $MAIN_STEPS, gamma=0.999 (таг $TAG)"
  python3 train.py "${TRAIN_COMMON[@]}" --envs "$MAIN_ENVS" --updates "$MAIN_UPDATES" \
      --steps "$MAIN_STEPS" --gamma 0.999 --lam 0.95 --ckpt-every 250 --tag "$TAG" || fail=1
  CKPT="outputs/params_fly-$TAG.pt"
  step "приёмка M1–M3 (3 эпизода по 8000 шагов = 33 игровые минуты)"
  python3 progress_eval.py --policy fly-sampled --checkpoint "$CKPT" \
      --episodes 3 --max-steps 8000 "${EVAL_COMMON[@]}" \
      --out "outputs/progress_$TAG.json" | tail -30
  echo
  echo "детали по эпизодам: outputs/progress_$TAG.json"
  ;;

*) echo "неизвестная стадия: $STAGE"; exit 2;;
esac

echo
if [ "$fail" -eq 0 ]; then
  echo "СТАДИЯ $STAGE: OK — можно идти дальше"
else
  echo "СТАДИЯ $STAGE: ЕСТЬ ПРОВАЛЫ — дальше не идти, чинить сначала"
fi
exit "$fail"
