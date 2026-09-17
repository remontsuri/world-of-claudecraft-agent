#!/usr/bin/env bash
# run_checks.sh — все офлайн-проверки проекта одной командой (без игры и GPU).
#
#   bash tools/run_checks.sh
#
# Годится и для CI: единственная внешняя зависимость — numpy (test_obs_layout.py
# дополнительно требует torch, т.к. импортирует fly_brain; без torch он скипается).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."

pass=0; fail=0; skip=0
run() {  # run "имя" команда...
  local name="$1"; shift
  echo "--- $name"
  if "$@"; then pass=$((pass+1)); else
    if [ "$name" = "test_obs_layout" ] && ! python3 -c "import torch" 2>/dev/null; then
      skip=$((skip+1)); echo "    скип: нет torch (запусти на машине с обучением)"
    else
      fail=$((fail+1))
    fi
  fi
}

run test_quest_oracle  python3 tools/test_quest_oracle.py
run test_obs_layout    python3 tools/test_obs_layout.py
run obs_layout_selftest python3 obs_layout.py

echo
printf '%-20s | %-14s | %s\n' LAYER EXPECTED STATUS
printf '%-20s | %-14s | %s\n' "таблицы оракула" "схема+коорд." "$([ $fail -eq 0 ] && echo OK || echo ПРОВАЛ)"
echo "пройдено=$pass провалено=$fail пропущено=$skip"
[ $fail -eq 0 ]
