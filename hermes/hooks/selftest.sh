#!/usr/bin/env bash
# Хуки — часть контракта, значит их поведение тоже проверяется, а не «вроде работает».
# Запуск: bash hermes/hooks/selftest.sh   (ожидаем: ВСЁ ЗЕЛЁНОЕ)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1

pass=0; fail=0
ok()   { echo "  OK    $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $1"; fail=$((fail+1)); }

expect_block() {   # $1 — описание, $2 — JSON события
  out=$(printf '%s' "$2" | bash hermes/hooks/guard.sh 2>/dev/null); rc=$?
  if [ $rc -ne 0 ] && grep -q '"continue": *false' <<< "$out"; then ok "$1"; else bad "$1 (код $rc: $out)"; fi
}
expect_allow() {   # $1 — описание, $2 — JSON события
  out=$(printf '%s' "$2" | bash hermes/hooks/guard.sh 2>/dev/null); rc=$?
  if [ $rc -eq 0 ] && grep -q '"continue": *true' <<< "$out"; then ok "$1"; else bad "$1 (код $rc: $out)"; fi
}
expect_json() {    # $1 — описание, $2 — команда хука
  out=$($2 2>/dev/null)
  if python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); assert "continue" in d and "message" in d' <<< "$out" 2>/dev/null; then
    ok "$1"
  else
    bad "$1 (не JSON или нет полей: ${out:0:80})"
  fi
}

echo "1) предохранитель guard.sh"
expect_block "force-push заблокирован"            '{"event":"pre_tool","tool":"Bash","command":"git push --force origin backup"}'
expect_block "зеркальный push заблокирован"       '{"event":"pre_tool","command":"git push --mirror origin"}'
expect_block "убийство hermes-agent заблокировано" '{"event":"pre_tool","command":"pkill -f hermes-agent"}'
expect_block "правка исходников игры заблокирована" '{"event":"pre_tool","paths":["D:/woc/src/sim/obs.ts"]}'
expect_block "коммит тяжёлых весов заблокирован"   '{"event":"pre_tool","command":"git add connectome-weights.feather"}'
expect_allow "обычный push разрешён"               '{"event":"pre_tool","command":"git push origin HEAD:refs/heads/backup"}'
expect_allow "запуск тестов разрешён"              '{"event":"pre_tool","command":"bash woof-agent/tools/run_tests.sh"}'
expect_allow "нейтральная команда не блокируется"  '{"event":"pre_tool","command":"ls -la"}'

echo "2) напоминания отдают валидный JSON"
expect_json "session_start" "bash hermes/hooks/session_start.sh"
expect_json "task_end"      "bash hermes/hooks/task_end.sh"

echo "3) напоминания знают про главное"
if bash hermes/hooks/session_start.sh | grep -q "Инварианты"; then ok "session_start перечисляет инварианты"; else bad "session_start без инвариантов"; fi
if bash hermes/hooks/session_start.sh | grep -q "ROADMAP\|Не закрыто"; then ok "session_start напоминает про незакрытые пункты"; else bad "session_start без роадмапа"; fi

echo
echo "хуки: passed=$pass failed=$fail"
if [ $fail -eq 0 ]; then echo "ВСЁ ЗЕЛЁНОЕ"; exit 0; else echo "ЕСТЬ ПРОВАЛЫ"; exit 1; fi
