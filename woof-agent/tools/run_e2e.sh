#!/usr/bin/env bash
# E2E автономного агента против полигона моста.
#   Фаза 1: агент -> Node-мост (:8791, fake_bridge.cjs)
#   Фаза 2: агент -> JAVA-мост (:8792, BridgeServer + UpstreamBackend) -> Node-мост
# Фаза 2 доказывает, что Java-мост говорит на том же контракте.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLASSES="$ROOT/build/classes"
STEPS="${STEPS:-120}"

cleanup() {
  [ -n "${BRIDGE_PID:-}" ] && kill "$BRIDGE_PID" 2>/dev/null
  [ -n "${JBRIDGE_PID:-}" ] && kill "$JBRIDGE_PID" 2>/dev/null
  return 0
}
trap cleanup EXIT

wait_port() {  # wait_port PORT
  for _ in $(seq 1 60); do (exec 3<>/dev/tcp/127.0.0.1/"$1") 2>/dev/null && return 0; sleep 0.2; done
  return 1
}

bash "$ROOT/tools/build.sh" >/dev/null || { echo "[e2e] build FAILED"; exit 1; }

run_phase() {  # run_phase N BRIDGE_URL TAG
  local n="$1" url="$2" tag="$3"
  local log="/tmp/e2e_agent_${tag}.log"
  java -Dfile.encoding=UTF-8 -Dsun.stdout.encoding=UTF-8 -Dsun.stderr.encoding=UTF-8 -cp "$CLASSES:$ROOT/libs/*" com.woof.agent.VoyagerAgent \
       --bridge "$url" --steps "$STEPS" --quiet >"$log" 2>&1
  local turn_ins qd viol
  turn_ins=$(grep -c "QUEST TURNED IN" "$log" || true)
  qd=$(grep -o "quests_done=[0-9]*" "$log" | tail -1 | cut -d= -f2)
  viol=$(curl -s http://127.0.0.1:8791/violations | grep -o '"count":[0-9]*' | cut -d: -f2)
  printf '%-12s | %-38s | %-16s | %s\n' "ФАЗА $n" "$url" "turn_in=$turn_ins quests_done=${qd:-0}" \
     "$( [ "${turn_ins:-0}" -ge 1 ] && [ "${viol:-1}" = "0" ] && echo OK || echo FAIL )"
  [ "${turn_ins:-0}" -ge 1 ] && [ "${qd:-0}" -ge 1 ] && [ "${viol:-1}" = "0" ]
}

echo "=== E2E: агент против полигона моста (steps=$STEPS)"
printf '%-12s | %-38s | %-16s | %s\n' LAYER TARGET RESULT STATUS

# --- Фаза 1: Node-мост ------------------------------------------------------
node "$ROOT/tools/fake_bridge.cjs" 8791 >/tmp/e2e_bridge.log 2>&1 &
BRIDGE_PID=$!
wait_port 8791 || { echo "[e2e] полигон не поднялся"; exit 1; }
curl -s http://127.0.0.1:8791/reset >/dev/null
PHASE1=1; run_phase 1 "http://127.0.0.1:8791/" node || PHASE1=0

# --- Фаза 2: Java-мост поверх Node-моста ------------------------------------
kill "$BRIDGE_PID" 2>/dev/null; wait "$BRIDGE_PID" 2>/dev/null
node "$ROOT/tools/fake_bridge.cjs" 8791 >/tmp/e2e_bridge2.log 2>&1 &
BRIDGE_PID=$!
wait_port 8791 || { echo "[e2e] полигон не поднялся"; exit 1; }
curl -s http://127.0.0.1:8791/reset >/dev/null

java -Dfile.encoding=UTF-8 -Dsun.stdout.encoding=UTF-8 -Dsun.stderr.encoding=UTF-8 -cp "$CLASSES:$ROOT/libs/*" com.woof.agent.bridge.BridgeMain \
     --port 8792 --upstream http://127.0.0.1:8791/ >/tmp/e2e_jbridge.log 2>&1 &
JBRIDGE_PID=$!
wait_port 8792 || { echo "[e2e] Java-мост не поднялся"; exit 1; }
PHASE2=1; run_phase 2 "http://127.0.0.1:8792/" java || PHASE2=0

echo
echo "логи: /tmp/e2e_agent_node.log /tmp/e2e_agent_java.log /tmp/e2e_bridge.log /tmp/e2e_jbridge.log"
grep -h "SUMMARY" /tmp/e2e_agent_node.log /tmp/e2e_agent_java.log 2>/dev/null
if [ "${PHASE1:-0}" = "1" ] && [ "${PHASE2:-0}" = "1" ]; then
  echo "УСПЕХ: квест сдан обоими путями (Node-мост и Java-мост), нарушений контракта нет"
  exit 0
fi
echo "ПРОВАЛ: см. таблицу выше и логи"
exit 1
