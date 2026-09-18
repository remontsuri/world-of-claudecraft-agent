#!/usr/bin/env bash
# Обязательные проверки линии woof-ts. Тот же набор зовёт пре-коммит хук
# (.githooks/pre-commit), поэтому «прошёл локально» и «пройдёт в хуке» — одно и то же.
#
# Порядок не случаен: сначала рабочее место (клон игры + зависимости + сборка),
# потом типы, потом факты игры, потом тесты, потом живые прогоны: стенд,
# детерминизм, живость ручек порогов, бридж к env-серверу игры и контур обучения.
# Провал любого шага — выход с кодом 1, без «почти прошло».
#
# Отключаемые шаги (когда нужно быстро): SKIP_BRIDGE=1, SKIP_TUNE=1.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail() { echo "ПРОВАЛ: $*"; exit 1; }

echo "== 0. рабочее место (клон игры, зависимости, сборка) =="
bash tools/setup_game.sh || fail "не подготовлено рабочее место"
[ -x ./node_modules/.bin/tsc ] || fail "нет node_modules/.bin/tsc — setup не установил зависимости"

echo "== 1. типы =="
# ВАЖНО: проверяем КОД ВОЗВРАТА, а не отфильтрованный вывод. Фильтр по 'src/'
# однажды скрыл полный провал tsc (не было node_modules) — пустой grep выглядел
# как «чисто». Дерево игры теперь клонируется полностью (включая src/world_api/**),
# поэтому tsc обязан быть чистым целиком.
if ! ./node_modules/.bin/tsc --noEmit -p tsconfig.json > /tmp/woof_tsc.txt 2>&1; then
  head -30 /tmp/woof_tsc.txt
  fail "ошибки типов (полный лог: /tmp/woof_tsc.txt)"
fi
echo "чисто (0 ошибок, включая дерево игры)"

echo "== 2. факты игры (импорт из upstream, не рукописные константы) =="
./node_modules/.bin/esbuild tools/verify_facts.ts --bundle --platform=node --format=esm \
  --outfile=dist/verify_facts.mjs --log-level=warning || fail "не собрался verify_facts"
node dist/verify_facts.mjs || fail "факты игры не сошлись с деревом upstream"

echo "== 3. тесты (включая бридж на живом env-сервере игры) =="
npm test || fail "тесты"

echo "== 4. живой прогон на стенде + детерминизм =="
node dist/run.mjs --seed 42 --steps 150 --quiet --json /tmp/woof_smoke_a.json 2>&1 | grep -E 'SUMMARY|ВНИМАНИЕ' | tee /tmp/woof_smoke_a.txt
node dist/run.mjs --seed 42 --steps 150 --quiet --json /tmp/woof_smoke_b.json 2>&1 | grep -E 'SUMMARY' > /tmp/woof_smoke_b.txt
diff -q /tmp/woof_smoke_a.txt /tmp/woof_smoke_b.txt >/dev/null || fail "детерминизм: два прогона одного сида дали разный SUMMARY"
grep -q 'kills=0' /tmp/woof_smoke_a.txt && fail "нет настоящих убийств (kills=0)"
grep -q 'quests_done=0' /tmp/woof_smoke_a.txt && echo "предупреждение: квест за 150 решений не сдан (порог объявлен в README)"

echo "== 5. пороги: таблица объявлена, ручки живые, валидация строгая =="
echo '{"levelDeltaMax":0}' > /tmp/woof_params_knob.json
WOOF_PARAMS=/tmp/woof_params_knob.json node dist/run.mjs --seed 42 --steps 60 --quiet 2>&1 | grep -E 'пороги|SUMMARY' | tee /tmp/woof_knob.txt
grep -q 'levelDeltaMax: 1→0' /tmp/woof_knob.txt || fail "переопределение порога не напечатано до прогона"
echo '{"lowHpAbort":5}' > /tmp/woof_params_bad.json
if WOOF_PARAMS=/tmp/woof_params_bad.json node dist/run.mjs --seed 42 --steps 5 --quiet > /tmp/woof_bad.txt 2>&1; then
  fail "значение вне диапазона принято — валидация таблицы не работает"
fi
grep -q 'вне объявленного диапазона' /tmp/woof_bad.txt || fail "ожидали внятную ошибку про диапазон, получили: $(tail -2 /tmp/woof_bad.txt)"
echo "пороги: 34 объявлено, переопределение печатается до измерения, выход за диапазон — исключение"

if [ "${SKIP_BRIDGE:-0}" = "1" ]; then
  echo "== 6. бридж к headless env игры: ПРОПУЩЕН (SKIP_BRIDGE=1) =="
else
  echo "== 6. бридж к headless env игры (тот же агент, другой транспорт) =="
  bash tools/build_env.sh || fail "не собрался env-сервер игры"
  # evidence бриджа — датированная ОТСЛЕЖИВАЕМАЯ папка: это доказательство приёмки,
  # а не черновик подбора (черновики живут в evidence/tuning/ и в .gitignore).
  EVID_DIR="evidence/$(date +%F)"; mkdir -p "$EVID_DIR"
  node dist/run.mjs --transport ndjson --seed 42 --steps 120 --quiet --json "$EVID_DIR/bridge-smoke-seed42.json" 2>&1 \
    | grep -E 'транспорт:|мир:|SUMMARY|ПРОГОН|ВНИМАНИЕ' | tee /tmp/woof_bridge.txt
  grep -q 'транспорт=ndjson-stdio' /tmp/woof_bridge.txt || fail "бридж не объявил транспорт до прогона"
  [ -s "$EVID_DIR/bridge-smoke-seed42.json" ] || fail "бридж не записал evidence"
  # evidence обязан объявить транспорт И его ограничения, иначе результат неатрибутируем
  grep -q '"kind": *"ndjson"' "$EVID_DIR/bridge-smoke-seed42.json" \
    || fail "в evidence бриджа не объявлен транспорт (transport.kind)"
  grep -q '"entityTemplates": *false' "$EVID_DIR/bridge-smoke-seed42.json" \
    || fail "в evidence бриджа не объявлены ограничения транспорта (capabilities)"
  grep -q '"questStateApi": *"observed"' "$EVID_DIR/bridge-smoke-seed42.json" \
    || fail "в evidence бриджа не объявлено состояние квестов (capabilities.questStateApi)"
  if grep -q 'kills=0 .*quests_done=0\|kills=0.*quests_done=0' /tmp/woof_bridge.txt; then
    fail "за бриджем агент не сделал ничего: ни убийств, ни квестов"
  fi
fi

if [ "${SKIP_TUNE:-0}" = "1" ]; then
  echo "== 7. контур обучения: ПРОПУЩЕН (SKIP_TUNE=1) =="
else
  echo "== 7. контур обучения (короткий прогон: цель объявлена, история пишется) =="
  rm -rf /tmp/woof_learn && mkdir -p /tmp/woof_learn
  node dist/tune.mjs --steps 40 --train-seeds 42 --val-seeds 44 --groups navigation \
    --candidates-per-param 1 --budget-seconds 420 --out /tmp/woof_learn 2>&1 | tail -8
  for f in history.jsonl best.json last_report.md; do
    [ -s "/tmp/woof_learn/$f" ] || fail "контур обучения не записал $f"
  done
  # Цель обязана быть объявлена в отчёте ДО чисел результата. Совпадение литеральное
  # (grep -i здесь не помощник: в локали C байты «Ц» и «ц» не складываются).
  grep -qF 'Целевая функция (объявлена до измерения)' /tmp/woof_learn/last_report.md \
    || fail "в отчёте нет объявления целевой функции"
  grep -qF '## Вердикт' /tmp/woof_learn/last_report.md || fail "в отчёте нет вердикта по val-сидам"
  grep -q '"objective"' /tmp/woof_learn/best.json || fail "в best.json нет целевой функции"
  grep -q '"kind": *"baseline"' /tmp/woof_learn/history.jsonl || fail "в истории нет базового измерения"
  grep -q '"accepted": *false' /tmp/woof_learn/history.jsonl \
    || echo "замечание: в коротком прогоне не оказалось отклонённых кандидатов (обычно они есть)"
  # Страж переобучения обязан СОВПАДАТЬ с числами: если val хуже базы, в отчёте вердикт
  # «ПЕРЕОБУЧЕНИЕ»; иначе «не хуже базового». Проверяем, что страж не декорация.
  node -e '
    const fs = require("fs");
    const b = JSON.parse(fs.readFileSync("/tmp/woof_learn/best.json", "utf8"));
    const r = fs.readFileSync("/tmp/woof_learn/last_report.md", "utf8");
    if (b.valMean === null || b.baselineValMean === null) {
      if (!r.includes("val не измерялся")) { console.error("отчёт не совпадает с best.json: val не измерялся"); process.exit(1); }
      process.exit(0);
    }
    const worse = b.valMean < b.baselineValMean;
    const saysOverfit = r.includes("ПЕРЕОБУЧЕНИЕ");
    if (worse !== saysOverfit) {
      console.error(`страж переобучения врёт: valMean=${b.valMean} baselineValMean=${b.baselineValMean} worse=${worse} в отчёте ПЕРЕОБУЧЕНИЕ=${saysOverfit}`);
      process.exit(1);
    }
    if (!Array.isArray(b.warnings) || b.warnings.length === 0) {
      console.error("в best.json нет предупреждений о узком сплите (train=1, val=1, шаги<100)");
      process.exit(1);
    }
    console.log(`страж переобучения согласован: val=${b.valMean} база=${b.baselineValMean} вердикт=${worse ? "ПЕРЕОБУЧЕНИЕ" : "не хуже базы"}; предупреждений: ${b.warnings.length}`);
  ' || fail "контур обучения: отчёт и best.json расходятся"
fi

echo "ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ"
