"""e2e_quest_cycle.py — production-level harness для верификации полного квестового цикла.

Цель: доказать что Agent → Policy → Skill → Bridge → Game → Verifier → Reward → Memory
работает end-to-end без вмешательства человека.

Требования:
- Запущенная игра (Chrome 9222 + Vite 5173 + Bridge 8791)
- Персонаж в игре, доступен для управления

Запуск:
    python e2e_quest_cycle.py

Exit code:
    0 — полный цикл пройден
    1 — цикл провален на каком-то этапе
"""
import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_env import BrowserEnv, BrowserBridgeError
from agent import Agent
from memory import ExperienceStore, WorldMemory
from goal_fsm import GoalFSM, QuestState
from policy import GoalManager
from observation import encode_observation
from reward import outcome_reward
from failure_analyzer import FailureAnalyzer
from autonomy import AutonomyLoop
from world_state import build_world_state
from action_mask import mask_candidates


class QuestCycleVerdict:
    """Результат одного этапа квестового цикла."""

    def __init__(self, stage: str):
        self.stage = stage
        self.passed = False
        self.details: Dict[str, Any] = {}
        self.decisions: List[Dict[str, Any]] = []
        self.error: Optional[str] = None
        self.start_time = time.time()
        self.end_time: Optional[float] = None

    def finish(self, passed: bool, details: Dict[str, Any] = None, error: str = None):
        self.passed = passed
        self.details = details or {}
        self.error = error
        self.end_time = time.time()

    def add_decision(self, step: int, action: str, reason: str, q_state: str,
                     candidates: List[str], goal: Optional[str]):
        self.decisions.append({
            "step": step,
            "action": action,
            "reason": reason,
            "q_state": q_state,
            "candidates": candidates,
            "goal": goal,
            "t": time.time(),
        })

    @property
    def duration(self) -> float:
        return (self.end_time or time.time()) - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "passed": self.passed,
            "duration": round(self.duration, 2),
            "details": self.details,
            "decisions_count": len(self.decisions),
            "error": self.error,
        }


class E2EQuestCycle:
    """Production-level harness использует AutonomyLoop и navigation sub-loop из play_autonomous.py."""

    STAGES = [
        "accept_quest",
        "find_objective",
        "navigate_to_objective",
        "combat_kills",
        "detect_ready",
        "find_turnin_npc",
        "return_to_giver",
        "turn_in",
        "receive_reward",
        "discover_next_quest",
    ]

    def __init__(self, max_steps_per_stage: int = 300, max_total_steps: int = 3000):
        self.max_steps_per_stage = max_steps_per_stage
        self.max_total_steps = max_total_steps
        self.verdicts: List[QuestCycleVerdict] = []
        self.total_steps = 0
        self.start_time = time.time()
        self.env: Optional[BrowserEnv] = None
        self.agent: Optional[Agent] = None
        self.world_mem: Optional[WorldMemory] = None
        self.fsm: Optional[GoalFSM] = None
        self.autonomy: Optional[AutonomyLoop] = None
        self.fail_analyzer = FailureAnalyzer(max_records=1000)
        self.telemetry: List[Dict[str, Any]] = []

    def setup(self):
        """Инициализация окружения и агента с AutonomyLoop."""
        print("[e2e] Initializing environment...", flush=True)

        # Проверяем bridge health
        import urllib.request
        try:
            with urllib.request.urlopen("http://127.0.0.1:8791/health", timeout=5) as resp:
                health = json.loads(resp.read())
                if not health.get("game"):
                    raise RuntimeError("Bridge health: game not ready")
        except Exception as e:
            raise RuntimeError(f"Bridge not available: {e}")

        self.env = BrowserEnv(player_class="warrior", max_steps=self.max_total_steps, seed=42)
        self.world_mem = WorldMemory()
        self.fsm = GoalFSM()
        self.autonomy = AutonomyLoop(min_dwell=20)

        mem = ExperienceStore()
        self.agent = Agent(
            self.env,
            mem,
            world_mem=self.world_mem,
            fsm=self.fsm,
        )

        print("[e2e] Environment ready (AutonomyLoop enabled)", flush=True)

    def run_stage(self, stage: str) -> QuestCycleVerdict:
        """Запуск одного этапа квестового цикла."""
        verdict = QuestCycleVerdict(stage)
        print(f"\n{'='*60}", flush=True)
        print(f"[e2e] Stage: {stage}", flush=True)
        print(f"{'='*60}", flush=True)

        try:
            if stage == "accept_quest":
                verdict = self._stage_accept_quest(verdict)
            elif stage == "find_objective":
                verdict = self._stage_find_objective(verdict)
            elif stage == "navigate_to_objective":
                verdict = self._stage_navigate_to_objective(verdict)
            elif stage == "combat_kills":
                verdict = self._stage_combat_kills(verdict)
            elif stage == "detect_ready":
                verdict = self._stage_detect_ready(verdict)
            elif stage == "find_turnin_npc":
                verdict = self._stage_find_turnin_npc(verdict)
            elif stage == "return_to_giver":
                verdict = self._stage_return_to_giver(verdict)
            elif stage == "turn_in":
                verdict = self._stage_turn_in(verdict)
            elif stage == "receive_reward":
                verdict = self._stage_receive_reward(verdict)
            elif stage == "discover_next_quest":
                verdict = self._stage_discover_next_quest(verdict)
            else:
                verdict.finish(False, error=f"Unknown stage: {stage}")
        except Exception as e:
            verdict.finish(False, error=f"Exception: {e}")
            traceback.print_exc()

        self.verdicts.append(verdict)
        status = "PASS" if verdict.passed else "FAIL"
        print(f"[e2e] Stage {stage}: {status} ({verdict.duration:.1f}s)", flush=True)
        if verdict.error:
            print(f"  Error: {verdict.error}", flush=True)

        return verdict

    def _run_autonomy_step(self, verdict: QuestCycleVerdict) -> Optional[Dict[str, Any]]:
        """Выполнить один шаг с AutonomyLoop и navigation sub-loop."""
        if self.total_steps >= self.max_total_steps:
            return None

        self.total_steps += 1
        step_num = self.total_steps

        info = self.env._last_info or {}
        ws = build_world_state(info, world_mem=self.world_mem)
        fsm_goal = self.fsm.goal if self.fsm else None

        # AutonomyLoop: before_action
        pre = None
        try:
            cands = list(self.agent.policy._candidates(info, ws, goal=fsm_goal) or [])
            pre = self.autonomy.before_action(info, ws, cands)
        except Exception as e:
            print(f"[e2e] before_action error: {e}", flush=True)

        # Navigation sub-loop (из play_autonomous.py)
        nav_iterations = 0
        max_nav_iterations = 3
        if pre and pre.get("nav_command"):
            nav_cmd = pre["nav_command"]
            while nav_cmd and nav_iterations < max_nav_iterations:
                try:
                    self.env.raw_call(nav_cmd)
                    nav_iterations += 1
                    # Проверяем прибытие
                    new_info = self.env._last_info or {}
                    new_ws = build_world_state(new_info, world_mem=self.world_mem)
                    new_cands = list(self.agent.policy._candidates(new_info, new_ws, goal=fsm_goal) or [])
                    new_pre = self.autonomy.before_action(new_info, new_ws, new_cands)
                    nav_cmd = new_pre.get("nav_command") if new_pre else None
                except Exception as e:
                    print(f"[e2e] nav error: {e}", flush=True)
                    break

        # Основной шаг агента
        rec = self.agent.step()

        # AutonomyLoop: after_action
        if pre:
            try:
                info_after = self.env._last_info or {}
                ws_after = build_world_state(info_after, world_mem=self.world_mem)
                self.autonomy.after_action(
                    rec.get("action", "?"),
                    info_after,
                    ws_after,
                    reward=rec.get("reward", 0.0),
                    goal=fsm_goal,
                )
            except Exception as e:
                print(f"[e2e] after_action error: {e}", flush=True)

        # Логируем решение
        action = rec.get("action", "?")
        cands = pre.get("candidates", []) if pre else []
        verdict.add_decision(
            step=step_num,
            action=action,
            reason=rec.get("outcome_kind", "?"),
            q_state=str(ws.get("navigation", {}).get("cell", "?")),
            candidates=cands,
            goal=fsm_goal,
        )

        self.telemetry.append({
            "step": step_num,
            "action": action,
            "verdict": rec.get("verdict"),
            "reward": rec.get("reward"),
            "goal": fsm_goal,
            "candidates": cands,
            "hp": info.get("player", {}).get("hp"),
            "kills": info.get("kills"),
            "deaths": info.get("deaths"),
            "nav_substeps": nav_iterations,
            "t": time.time(),
        })

        return rec

    def _stage_accept_quest(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: принять квест."""
        for _ in range(self.max_steps_per_stage):
            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

            if rec.get("action") == "accept_quest" and rec.get("verdict", "").upper() == "SUCCESS":
                info = self.env._last_info or {}
                quests = info.get("quests", {}).get("active", [])
                if quests:
                    verdict.finish(True, details={
                        "quest_id": quests[0].get("id"),
                        "quest_name": quests[0].get("name"),
                    })
                    return verdict

        verdict.finish(False, error="Failed to accept quest within step limit")
        return verdict

    def _stage_find_objective(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: найти objective квеста."""
        for _ in range(50):
            info = self.env._last_info or {}
            quests = info.get("quests", {}).get("active", [])
            if quests:
                objectives = quests[0].get("objectives", [])
                if objectives:
                    verdict.finish(True, details={
                        "objective_type": objectives[0].get("type"),
                        "target": objectives[0].get("targetMobId"),
                        "current": objectives[0].get("current"),
                        "required": objectives[0].get("required"),
                    })
                    return verdict
            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

        verdict.finish(False, error="No objective found")
        return verdict

    def _stage_navigate_to_objective(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: навигация к objective."""
        for _ in range(self.max_steps_per_stage):
            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

            if rec.get("action") in ("navigate", "farm"):
                verdict.finish(True, details={"action": rec.get("action")})
                return verdict

        verdict.finish(False, error="Agent never chose navigate/farm")
        return verdict

    def _stage_combat_kills(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: убить 8 мобов."""
        initial_kills = (self.env._last_info or {}).get("kills", 0)

        for _ in range(self.max_steps_per_stage):
            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

            info = self.env._last_info or {}
            kills = info.get("kills", 0)
            quests = info.get("quests", {}).get("active", [])

            for q in quests:
                for obj in q.get("objectives", []):
                    if obj.get("type") == "kill":
                        current = obj.get("current", 0)
                        required = obj.get("required", 8)
                        if current >= required:
                            verdict.finish(True, details={
                                "kills": kills,
                                "objective_progress": f"{current}/{required}",
                            })
                            return verdict

            if kills >= initial_kills + 8:
                verdict.finish(True, details={"kills": kills})
                return verdict

        verdict.finish(False, error=f"Not enough kills after {self.max_steps_per_stage} steps")
        return verdict

    def _stage_detect_ready(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: детекция READY_TO_TURN_IN."""
        for _ in range(50):
            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

            info = self.env._last_info or {}
            quests = info.get("quests", {}).get("ready", [])
            if quests:
                verdict.finish(True, details={"ready_quest_id": quests[0].get("id")})
                return verdict

        verdict.finish(False, error="READY_TO_TURN_IN not detected")
        return verdict

    def _stage_find_turnin_npc(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: найти turn-in NPC (FSM переключился в RETURN_TO_GIVER)."""
        for _ in range(50):
            if self.fsm and self.fsm.state == QuestState.RETURN_TO_GIVER:
                verdict.finish(True, details={"fsm_state": self.fsm.state.name})
                return verdict

            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

        verdict.finish(False, error="FSM did not switch to RETURN_TO_GIVER")
        return verdict

    def _stage_return_to_giver(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: вернуться к гиверу."""
        for _ in range(self.max_steps_per_stage):
            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

            if rec.get("action") == "return_to_giver" and rec.get("verdict", "").upper() == "SUCCESS":
                info = self.env._last_info or {}
                dist = info.get("distance_to_giver", 999)
                verdict.finish(True, details={"distance_to_giver": dist})
                return verdict

        verdict.finish(False, error="Failed to return to giver")
        return verdict

    def _stage_turn_in(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: сдать квест."""
        for _ in range(50):
            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

            if rec.get("action") == "turn_in_quest" and rec.get("verdict", "").upper() == "SUCCESS":
                verdict.finish(True, details={"verdict": "SUCCESS"})
                return verdict

        verdict.finish(False, error="Turn-in failed")
        return verdict

    def _stage_receive_reward(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: получить награду."""
        for _ in range(50):
            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

            info = self.env._last_info or {}
            done_quests = info.get("quests", {}).get("done", [])
            if done_quests:
                verdict.finish(True, details={
                    "done_quest_id": done_quests[0].get("id"),
                    "xp": info.get("xp"),
                    "copper": info.get("copper"),
                })
                return verdict

        verdict.finish(False, error="Reward not received")
        return verdict

    def _stage_discover_next_quest(self, verdict: QuestCycleVerdict) -> QuestCycleVerdict:
        """Этап: обнаружить следующий квест."""
        for _ in range(self.max_steps_per_stage):
            rec = self._run_autonomy_step(verdict)
            if rec is None:
                break

            if rec.get("action") == "accept_quest" and rec.get("verdict", "").upper() == "SUCCESS":
                info = self.env._last_info or {}
                quests = info.get("quests", {}).get("active", [])
                if quests:
                    verdict.finish(True, details={
                        "new_quest_id": quests[0].get("id"),
                    })
                    return verdict

        verdict.finish(False, error="Next quest not discovered")
        return verdict

    def run(self) -> bool:
        """Запуск полного квестового цикла."""
        print("=" * 60, flush=True)
        print("E2E Quest Cycle Harness (with AutonomyLoop)", flush=True)
        print("=" * 60, flush=True)

        try:
            self.setup()
        except Exception as e:
            print(f"[e2e] Setup failed: {e}", flush=True)
            return False

        all_passed = True
        for stage in self.STAGES:
            verdict = self.run_stage(stage)
            if not verdict.passed:
                all_passed = False
                print(f"\n[e2e] Cycle FAILED at stage: {stage}", flush=True)
                break

        self._print_report(all_passed)
        return all_passed

    def _print_report(self, all_passed: bool):
        """Вывод итогового отчёта."""
        total_time = time.time() - self.start_time

        print("\n" + "=" * 60, flush=True)
        print("E2E QUEST CYCLE REPORT", flush=True)
        print("=" * 60, flush=True)

        for v in self.verdicts:
            status = "PASS" if v.passed else "FAIL"
            print(f"  [{status}] {v.stage}: {v.duration:.1f}s", flush=True)
            if v.error:
                print(f"         Error: {v.error}", flush=True)

        print("-" * 60, flush=True)
        print(f"Total steps: {self.total_steps}", flush=True)
        print(f"Total time: {total_time:.1f}s", flush=True)
        print(f"Result: {'PASS' if all_passed else 'FAIL'}", flush=True)
        print("=" * 60, flush=True)

        report = {
            "result": "PASS" if all_passed else "FAIL",
            "total_steps": self.total_steps,
            "total_time": total_time,
            "stages": [v.to_dict() for v in self.verdicts],
            "telemetry": self.telemetry,
        }
        report_path = os.path.join(os.path.dirname(__file__), "e2e_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nReport saved to: {report_path}", flush=True)


def main():
    harness = E2EQuestCycle(max_steps_per_stage=300, max_total_steps=3000)
    success = harness.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
