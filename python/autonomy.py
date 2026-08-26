"""autonomy.py — замкнутый автономный контур (ARCHITECTURE.md §13).

Склеивает уже готовые модули в одну петлю и подключается к agent.py
ДВУМЯ вызовами, не переписывая его цикл:

    before_action(info, ws)  -> отфильтрованные кандидаты + subgoal
    after_action(...)        -> SUCCESS/FAILURE/NO_OP + recovery + запись

Почему обёртка, а не правка _cycle: цикл agent.py уже несёт FSM, reward,
Q-обучение и replay. Вклиниваться внутрь — значит рисковать регрессом в
рабочем коде. Обёртка добавляет уровни, ничего не отбирая.
"""
import time
from typing import Any, Dict, List, Optional

from observation import encode_observation
from action_mask import mask_candidates, why_blocked, index_of
from planner import Planner
from progress import detect_progress, classify_outcome
from skill_contracts import check_preconditions, verify_postconditions
from recovery import RecoveryTracker
from anti_loop import LoopGuard

# recovery_action -> навык, которым он исполняется.
# Если действия нет в карте, контур его не форсирует (пусть решает политика).
RECOVERY_TO_SKILL: Dict[str, str] = {
    "sell_junk": "sell_junk",
    "buy_tool": "buy",
    "retreat_and_heal": "heal",
    "navigate_to_vendor": "explore",
    "navigate_to_node": "explore",
    "navigate_to_giver": "explore",
    "find_alternate_vendor": "explore",
    "find_giver": "explore",
    "explore_town": "explore",
    "explore_for_node": "explore",
    "explore_for_mob": "explore",
    "alternate_route": "explore",
    "approach_mob": "farm",
    "select_weaker_target": "farm",
    "turn_in_ready_quest": "turn_in_quest",
    "continue_objective": None,
    "next_objective": None,
    "next_quest": None,
    "replan": None,
    "abandon_objective": None,
    "skip_sell": None,
    "skip_heal": None,
    "skip_craft": None,
    "skip_corpse": None,
    "unstuck_jump": "explore",
    "inspect_tool_node": None,
    "re_evaluate_quest": None,
    "finish_combat": "farm",
    "gather_reagents": "gather",
    "navigate_to_station": "explore",
    "farm_for_loot": "farm",
    "retreat": "explore",
}


class AutonomyLoop:
    """Один экземпляр на прогон агента."""

    def __init__(self, min_dwell: int = 20, loop_window: int = 40,
                 max_recovery_attempts: int = 3):
        self.planner = Planner(min_dwell=min_dwell)
        self.guard = LoopGuard(window=loop_window)
        self.recovery = RecoveryTracker(max_attempts=max_recovery_attempts)
        self.obs_before: Optional[Dict[str, Any]] = None
        self.last: Dict[str, Any] = {}
        self.stats = {
            "steps": 0, "success": 0, "failure": 0, "no_op": 0,
            "masked_out": 0, "loops_tripped": 0, "recoveries": 0,
            "subgoals": {},
        }

    # ------------------------------------------------------------ pre-action
    def before_action(self, info: Dict[str, Any], ws: Dict[str, Any],
                      candidates: List[str]) -> Dict[str, Any]:
        """Что политике разрешено делать сейчас и зачем.

        Возвращает {candidates, subgoal, forced_skill, obs, blocked}.
        forced_skill не None -> контур настаивает (recovery/loop), политика
        может его использовать вместо своего выбора.
        """
        obs = encode_observation(ws, info)
        self.obs_before = obs

        urgent = bool((obs.get("player") or {}).get("dead"))
        subgoal = self.planner.step(obs, force=urgent)

        # 1. отсечь то, чьи предусловия не выполнены
        masked = mask_candidates(list(candidates or []), obs)
        # считаем именно отсеянные кандидаты: mask_candidates может подставить
        # explore-fallback, поэтому разница длин занижала бы счётчик
        dropped = [c for c in (candidates or []) if c not in masked]
        if dropped:
            self.stats["masked_out"] += len(dropped)

        # 2. снять действия на cooldown-е после зафиксированного цикла
        masked = self.guard.filter_candidates(masked)

        # 3. форс: сначала цикл, потом subgoal
        forced = None
        if self.guard.is_looping():
            trip = self.guard.trip()
            self.stats["loops_tripped"] += 1
            forced = RECOVERY_TO_SKILL.get(trip["recovery_action"])
            self.last["loop"] = trip
        else:
            self.last["loop"] = None
            sg_skill = (subgoal or {}).get("skill")
            if sg_skill and check_preconditions(sg_skill, obs)["ok"]:
                forced = sg_skill

        if forced and forced not in masked:
            # форсируем только исполнимое
            if forced == "explore" or check_preconditions(forced, obs)["ok"]:
                masked = [forced] + masked

        name = (subgoal or {}).get("subgoal") or "?"
        self.stats["subgoals"][name] = self.stats["subgoals"].get(name, 0) + 1

        return {
            "candidates": masked,
            "subgoal": subgoal,
            "forced_skill": forced,
            "obs": obs,
            "blocked": self.guard.blocked_actions(),
        }

    # ----------------------------------------------------------- post-action
    def after_action(self, action: str, info_after: Dict[str, Any],
                     ws_after: Dict[str, Any],
                     reward: float = 0.0,
                     goal: Optional[str] = None) -> Dict[str, Any]:
        """Проверить постусловия, решить recovery, записать в LoopGuard."""
        obs_after = encode_observation(ws_after, info_after)
        obs_before = self.obs_before or obs_after

        progress = detect_progress(obs_before, obs_after)
        outcome = classify_outcome(progress)
        post = verify_postconditions(action, progress)

        # Контракт строже общей классификации: если постусловия навыка не
        # выполнены, это не SUCCESS, даже если что-то в мире шевельнулось.
        result = outcome
        if post.get("result") == "FAILURE" and outcome == "SUCCESS":
            result = "NO_OP"
        if outcome == "FAILURE":
            result = "FAILURE"

        failure_reason = None
        recovery = None
        if result != "SUCCESS":
            failed_pre = why_blocked(action, obs_before)
            failure_reason = (failed_pre[0] if failed_pre
                              else (post.get("missing") or ["no_effect"])[0])
            rec = self.recovery.next_action(action, failure_reason, obs_after)
            recovery = rec
            self.stats["recoveries"] += 1
        else:
            self.recovery.on_success(action)

        made_progress = bool(progress.get("any_progress")) or result == "SUCCESS"
        self.guard.observe(action, made_progress,
                           state_key=str(obs_after.get("navigation", {}).get("cell") or ""))

        self.stats["steps"] += 1
        self.stats[result.lower()] = self.stats.get(result.lower(), 0) + 1

        # subgoal считаем выполненным только по фактическому успеху
        if result == "SUCCESS":
            cur = self.planner.current or {}
            if cur.get("skill") == action:
                self.planner.on_subgoal_done()

        rec_out = {
            "skill": action,
            "skill_result": result,
            "failure_reason": failure_reason,
            "recovery": recovery,
            "progress_delta": progress,
            "postconditions": post,
            "subgoal": (self.planner.current or {}).get("subgoal"),
            "goal": goal,
            "reward": reward,
            "action_index": index_of(action),
            "timestamp": time.time(),
        }
        self.last["record"] = rec_out
        self.obs_before = obs_after
        return rec_out

    # ---------------------------------------------------------------- report
    def summary(self) -> Dict[str, Any]:
        s = dict(self.stats)
        n = max(1, s.get("steps", 0))
        s["success_rate"] = round(s.get("success", 0) / n, 4)
        s["no_op_rate"] = round(s.get("no_op", 0) / n, 4)
        s["failure_rate"] = round(s.get("failure", 0) / n, 4)
        return s
