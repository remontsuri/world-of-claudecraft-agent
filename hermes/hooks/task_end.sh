#!/usr/bin/env bash
# Хук конца задачи: прогнать релевантные проверки и не дать потерять результат.
# Контракт: hermes/hooks/README.md
set -uo pipefail

ROOT="${WOC_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT" 2>/dev/null || { echo '{"continue": true, "message": "репозиторий не найден"}'; exit 0; }

declare -a parts=()
add() { parts+=("$1"); }

trunc() {  # обрезка по СИМВОЛАМ: cut -c режет байты и превращает кириллицу в мусор
  T="$1" N="${2:-140}" python3 -c 'import os; t=os.environ["T"]; n=int(os.environ["N"]); print(t if len(t)<=n else t[:n-1]+"…")' 2>/dev/null || printf '%s' "$1"
}


changed=$(git status --porcelain 2>/dev/null | awk '{print $2}' | head -40)

run_note() {   # $1 — что изменилось, $2 — команда, $3 — ожидаемая строка успеха
  add "Проверка: $2 (ожидаем: $3)"
}

if grep -qE '^woof-agent/' <<< "$changed"; then
  run_note "" "bash woof-agent/tools/build.sh && bash woof-agent/tools/run_tests.sh" "build ok / tests passed=3 failed=0"
  run_note "" "bash woof-agent/tools/run_e2e.sh (перед пушем)" "УСПЕХ ... нарушений контракта нет"
fi
if grep -qE '^knowledge/|^hermes/' <<< "$changed"; then
  run_note "" "bash hermes/hooks/selftest.sh" "хуки: passed=17 failed=0"
fi
if grep -qE '^archive/' <<< "$changed"; then
  add "Правка в archive/: архив заморожен 2026-09-18, итоги fly-линии задним числом не переписываем. Новый факт — отдельной строкой с датой в archive/fly-line/README.md."
fi

# Незаписанное знание: правки в коде без правок в документах
if [ -n "$changed" ] && ! grep -qE '^(knowledge/|woof-agent/ROADMAP.md|woof-agent/ARCHITECTURE.md|AGENTS.md)' <<< "$changed"; then
  add "Возможная потеря: код менялся, а ROADMAP/knowledge — нет. Если выяснился факт, грабля или новое поведение — записать в knowledge/ и woof-agent/ROADMAP.md сегодня, иначе знание умрёт с сессией."
fi

# Что осталось открытым по активной линии
roadmap="$ROOT/woof-agent/ROADMAP.md"
if [ -f "$roadmap" ]; then
  first_open=$(grep -E '^\| J[0-9]+ .*⬜' "$roadmap" | head -1 | sed 's/|/ /g' | tr -s ' ' | sed 's/^ //')
  [ -n "$first_open" ] && add "Следующий незакрытый пункт:$(trunc "$first_open" 150)"
fi

# Незакоммиченное перед «готово»
if [ -n "$changed" ]; then
  add "Незакоммиченные изменения: $(wc -l <<< "$changed" | tr -d ' ') файлов. Либо коммит, либо явно сказать пользователю, что оставлено и почему."
fi

msg=$(printf '%s\n' "${parts[@]}")
MSG="$msg" python3 -c 'import json,os; print(json.dumps({"continue": True, "message": os.environ["MSG"]}, ensure_ascii=False))' 2>/dev/null \
  || printf '{"continue": true, "message": "%s"}\n' "$(printf '%s' "$msg" | tr '\n' ' ' | sed 's/"/\\"/g')"
