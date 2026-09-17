#!/usr/bin/env bash
# Юнит/интеграционные тесты без браузера и без игры.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Русский текст из java/javac иначе превращается в ?????: в контейнере локаль не UTF-8.
export JAVA_TOOL_OPTIONS="-Dfile.encoding=UTF-8 -Dsun.stdout.encoding=UTF-8 -Dsun.stderr.encoding=UTF-8"
CLASSES="$ROOT/build/classes"

bash "$ROOT/tools/build.sh" >/dev/null || { echo "[tests] build FAILED"; exit 1; }
# тесты лежат отдельно и подключаются к уже собранным классам агента
mkdir -p "$CLASSES/test"
javac -encoding UTF-8 -cp "$CLASSES:$ROOT/libs/*" -d "$CLASSES/test" "$ROOT"/tests/*.java \
  || { echo "[tests] компиляция тестов FAILED"; exit 1; }

# Осиротевший fake_cdp от прошлого прогона держит 9231/9232: новый не стартует,
# а проверка готовности порта проходит - тест уходит работать против чужого процесса.
# Убиваем только СВОИ инструменты (по точному пути в cmdline) и только их;
# всё чужое на этих портах - повод остановиться и сказать, кто это.
for port in 8791 9231 9232; do
  pid=$(ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $NF}' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  [ -z "${pid:-}" ] && continue
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || echo "")
  case "$cmd" in
    *fake_cdp.cjs*|*fake_bridge.cjs*|*browser_bridge.cjs*)
      echo "[tests] порт $port держит наш процесс $pid — убираю: $cmd"; kill "$pid" 2>/dev/null; sleep 0.5 ;;
    *)
      echo "[tests] ОСТАНОВ: порт $port занят посторонним процессом $pid: $cmd"; exit 1 ;;
  esac
done

node "$ROOT/tools/fake_cdp.cjs" 9231 9232 >/tmp/fake_cdp.log 2>&1 &
FAKE_PID=$!
for i in $(seq 1 40); do (exec 3<>/dev/tcp/127.0.0.1/9231) 2>/dev/null && break; sleep 0.1; done

PASS=0; FAIL=0
ROWS=""
for t in TestSkillIndex TestCdpClient TestJavaBridge; do
  echo "--- $t"
  log="/tmp/tests_$t.log"; : > "$log"
  # Без -Dfile.encoding русский текст java превращается в "?????": вердикт нечитаем.
  java -cp "$CLASSES/test:$CLASSES:$ROOT/libs/*" -Drepo.root="$ROOT" \
       -Dfile.encoding=UTF-8 -Dsun.stdout.encoding=UTF-8 -Dsun.stderr.encoding=UTF-8 \
       "$t" > "$log" 2>&1
  cat "$log"
  verdict=$(grep -E "^(PASS|FAIL)" "$log" | tail -1)
  if [ "${verdict#PASS}" != "$verdict" ]; then PASS=$((PASS+1)); st=OK; else FAIL=$((FAIL+1)); st="см. $log"; fi
  ROWS="$ROWS$(printf '%-18s | %-8s | %s\n' "$t" "$st" "$verdict")\n"
done
kill $FAKE_PID 2>/dev/null

echo
printf '%-18s | %-8s | %s\n' LAYER EXPECTED STATUS
printf "$ROWS"
echo "tests passed=$PASS failed=$FAIL"
[ $FAIL -eq 0 ]
