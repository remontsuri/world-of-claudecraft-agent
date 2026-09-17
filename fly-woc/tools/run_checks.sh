#!/usr/bin/env bash
# run_checks.sh — что обязано быть зелёным до обучения и до пуша.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
run() { echo; echo "=== $* ==="; "$@"; local rc=$?; [ $rc -eq 0 ] || { echo "ПРОВАЛ: $*"; fail=1; }; }

run python3 tools/test_control_graph.py
run python3 tools/test_quest_oracle.py
run python3 tools/test_quest_oracle.py --parity
run python3 tools/test_obs_layout.py
run python3 -m py_compile train.py progress_eval.py live_agent.py check_io.py fly_brain.py agent.py device_utils.py
run python3 -m compileall -q ../src/fly_brain
run python3 tools/test_device.py
run python3 tools/test_parallel_envs.py
run python3 tools/gpu_check.py --device cpu

echo
if [ $fail -eq 0 ]; then echo "ВСЁ ЗЕЛЁНОЕ"; else echo "ЕСТЬ ПРОВАЛЫ"; fi
exit $fail
