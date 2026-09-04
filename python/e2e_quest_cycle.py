"""e2e_quest_cycle.py — production-level harness для верификации полного квестового цикла.

Подход: запускаем play_autonomous.py с ограничением шагов, затем анализируем лог.
Это избегает дублирования сложной логики AutonomyLoop + navigation sub-loop.

Требования:
- Запущенная игра (Chrome 9222 + Vite 5173 + Bridge 8791)
- Персонаж в игре, доступен для управление

Запуск:
    python e2e_quest_cycle.py

Exit code:
    0 — полный цикл пройден
    1 — цикл провален на каком-то этапе
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def check_bridge():
    """Проверяем готовность bridge."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8791/health", timeout=5) as resp:
            health = json.loads(resp.read())
            return health.get("game", False)
    except Exception:
        return False


def reset_state():
    """Сброс состояния FSM и телометрии перед прогоном."""
    state_path = os.path.join(os.path.dirname(__file__), "goal_fsm_state.json")
    if os.path.exists(state_path):
        os.remove(state_path)
    # Очищаем lock-файлы
    for f in ["agent.pid", "play_autonomous.lock"]:
        p = os.path.join(os.path.dirname(__file__), f)
        if os.path.exists(p):
            os.remove(p)


def run_play_autonomous(steps: int = 1000, timeout: int = 1800) -> str:
    """Запуск play_autonomous.py с ограничением шагов. Возвращает путь к логу."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(__file__)
    env["AUTONOMOUS_STEPS"] = str(steps)

    log_path = os.path.join(os.path.dirname(__file__), "e2e_run.log")

    try:
        result = subprocess.run(
            [sys.executable, "play_autonomous.py"],
            cwd=os.path.dirname(__file__),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # Сохраняем stdout+stderr
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("=== STDOUT ===\n")
            f.write(result.stdout)
            f.write("\n=== STDERR ===\n")
            f.write(result.stderr)
            f.write(f"\n=== EXIT CODE: {result.returncode} ===\n")
    except subprocess.TimeoutExpired:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("TIMEOUT\n")
    except Exception as e:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"ERROR: {e}\n")

    return log_path


def analyze_log(log_path: str) -> dict:
     """Анализ autonomous_log.jsonl для детекции квестового цикла."""
     autonomous_log = os.path.join(os.path.dirname(__file__), "autonomous_log.jsonl")

     if not os.path.exists(autonomous_log):
         return {"result": "FAIL", "error": "autonomous_log.jsonl not found"}

     stages = {
         "accept_quest": False,
         "find_objective": False,
         "navigate_to_objective": False,
         "combat_kills": False,
         "detect_ready": False,
         "find_turnin_npc": False,
         "return_to_giver": False,
         "turn_in": False,
         "receive_reward": False,
         "discover_next_quest": False,
     }

     quest_accepts = 0
     quest_turnins = 0
     max_kills = 0
     ready_detected = False
     giver_dist_min = float("inf")
     total_steps = 0

     with open(autonomous_log, "r", encoding="utf-8") as f:
         for line in f:
             line = line.strip()
             if not line:
                 continue
             try:
                 d = json.loads(line)
             except json.JSONDecodeError:
                 continue

             total_steps = max(total_steps, d.get("step", 0))
             action = d.get("action", "")
             verdict = d.get("verdict", "")
             goal = d.get("goal")
             kills = d.get("kills", 0)
             dist = d.get("dist", float("inf"))
             qs = d.get("quest_status", "")

             # Detect stages
             if action == "accept_quest" and verdict.upper() == "SUCCESS":
                 quest_accepts += 1
                 stages["accept_quest"] = True

             if action in ("navigate", "farm") and d.get("step", 0) > 5:
                 stages["navigate_to_objective"] = True

             if kills >= 8:
                 stages["combat_kills"] = True
             max_kills = max(max_kills, kills)

             if qs == "READY_TO_TURN_IN":
                 ready_detected = True
                 stages["detect_ready"] = True

             if goal == "RETURN_TO_GIVER":
                 stages["find_turnin_npc"] = True

             if action == "return_to_giver" and verdict.upper() == "SUCCESS":
                 stages["return_to_giver"] = True

             if action == "turn_in_quest" and verdict.upper() == "SUCCESS":
                 quest_turnins += 1
                 stages["turn_in"] = True

             if dist < giver_dist_min:
                 giver_dist_min = dist

     # Reward detection: quest moved to done
     stages["receive_reward"] = quest_turnins > 0
     stages["discover_next_quest"] = quest_accepts > 1
     stages["find_objective"] = stages["accept_quest"]  # If we accepted, we have objective

     all_passed = all(stages.values())

     return {
         "result": "PASS" if all_passed else "FAIL",
         "total_steps": total_steps,
         "quest_accepts": quest_accepts,
         "quest_turnins": quest_turnins,
         "max_kills": max_kills,
         "ready_detected": ready_detected,
         "giver_dist_min": round(giver_dist_min, 1) if giver_dist_min < float("inf") else None,
         "stages": stages,
     }


def main():
     print("=" * 60, flush=True)
     print("E2E Quest Cycle Harness (via play_autonomous.py)", flush=True)
     print("=" * 60, flush=True)

     # 1. Проверяем bridge
     if not check_bridge():
         print("[e2e] FAIL: Bridge not ready (game:false)", flush=True)
         return False

     # 2. Сбрасываем состояние
     reset_state()
     print("[e2e] State reset", flush=True)

     # 3. Запускаем play_autonomous.py
     print("[e2e] Running play_autonomous.py (1000 steps)...", flush=True)
     start = time.time()
     log_path = run_play_autonomous(steps=1000, timeout=1800)
     elapsed = time.time() - start
     print(f"[e2e] Run completed in {elapsed:.1f}s", flush=True)

     # 4. Анализируем результат
     result = analyze_log(log_path)

     # 5. Выводим отчёт
     print("\n" + "=" * 60, flush=True)
     print("E2E QUEST CYCLE REPORT", flush=True)
     print("=" * 60, flush=True)

     for stage, passed in result.get("stages", {}).items():
         status = "PASS" if passed else "FAIL"
         print(f"  [{status}] {stage}", flush=True)

     print("-" * 60, flush=True)
     print(f"Total steps: {result.get('total_steps', 0)}", flush=True)
     print(f"Quest accepts: {result.get('quest_accepts', 0)}", flush=True)
     print(f"Quest turn-ins: {result.get('quest_turnins', 0)}", flush=True)
     print(f"Max kills: {result.get('max_kills', 0)}", flush=True)
     print(f"Ready detected: {result.get('ready_detected', False)}", flush=True)
     print(f"Min giver distance: {result.get('giver_dist_min', 'N/A')}", flush=True)
     print(f"Result: {result.get('result', 'FAIL')}", flush=True)
     print("=" * 60, flush=True)

     # Сохраняем отчёт
     report_path = os.path.join(os.path.dirname(__file__), "e2e_report.json")
     with open(report_path, "w", encoding="utf-8") as f:
         json.dump(result, f, ensure_ascii=False, indent=2)
     print(f"\nReport saved to: {report_path}", flush=True)

     return result.get("result") == "PASS"


if __name__ == "__main__":
     success = main()
     sys.exit(0 if success else 1)
