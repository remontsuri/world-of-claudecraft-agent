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
from navigation import (NavigationController, DISTANCE_PRECONDITIONS,
                        target_kind_for_subgoal)
from decision_context import DecisionContext
from recovery import (RecoveryTracker, ObjectiveBlacklist,
                      plan_recovery, assert_recovery_executable)
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
        # P0.7: отказ от цели должен РЕАЛЬНО менять поведение, а не быть
        # сигналом «пусть policy решит» (она выбирала то же самое снова).
        self.blacklist = ObjectiveBlacklist(cooldown_steps=60)
        # P0.6: падаем на старте, если какая-то ветка recovery неисполнима
        assert_recovery_executable()
        # что контур обязан сделать на следующем шаге по итогам recovery
        self.pending_recovery = None
        self.nav = NavigationController()
        self.nav_target_before = None
        self.obs_before: Optional[Dict[str, Any]] = None
        self.last: Dict[str, Any] = {}
        self.stats = {
            "steps": 0, "success": 0, "failure": 0, "no_op": 0,
            "masked_out": 0, "loops_tripped": 0, "recoveries": 0,
            "subgoals": {},
        }

    # ------------------------------------------------------------ pre-action
    @staticmethod
    def _objective_key(obs):
        """Стабильный ключ текущей цели для блеклиста."""
        q = (obs or {}).get("quest") or {}
        nxt = q.get("next_objective") or {}
        if nxt:
            return "%s:%s:%s" % (nxt.get("quest_id"), nxt.get("type"),
                                 nxt.get("target_mob_id") or nxt.get("item_id")
                                 or nxt.get("node_type") or "")
        return None

    def before_action(self, info: Dict[str, Any], ws: Dict[str, Any],
                      candidates: List[str]) -> Dict[str, Any]:
        """Что политике разрешено делать сейчас и зачем.

        Возвращает {candidates, subgoal, forced_skill, obs, blocked}.
        forced_skill не None -> контур настаивает (recovery/loop), политика
        может его использовать вместо своего выбора.
        """
        obs = encode_observation(ws, info)
        self.obs_before = obs
        self.blacklist.tick()

        urgent = bool((obs.get("player") or {}).get("dead"))
        subgoal = self.planner.step(obs, force=urgent)

        # Цель под отказом (P0.7): не берём её снова, пока не истёк cooldown.
        # Раньше abandon_objective ничего не менял, и policy выбирала ту же
        # цель: failure -> abandon -> policy -> тот же навык -> failure.
        if subgoal and self.blacklist.is_blocked(self._objective_key(obs)):
            self.planner.force_replan()
            self.stats["blacklist_skips"] = self.stats.get("blacklist_skips", 0) + 1
            subgoal = self.planner.step(obs, force=True)

        # 1. отсечь то, чьи предусловия не выполнены
        masked = mask_candidates(list(candidates or []), obs)
        # считаем именно отсеянные кандидаты: mask_candidates может подставить
        # explore-fallback, поэтому разница длин занижала бы счётчик
        dropped = [c for c in (candidates or []) if c not in masked]
        if dropped:
            self.stats["masked_out"] += len(dropped)

        # 2. снять действия на cooldown-е после зафиксированного цикла
        masked = self.guard.filter_candidates(masked)

        # 3. форс: recovery -> цикл -> subgoal
        forced = None
        nav_command = None
        nav_status = None

        # 3a. P0.6: незакрытая стратегия восстановления имеет приоритет —
        # иначе «recovery» остаётся строчкой в логе, а поведение не меняется.
        pend = self.pending_recovery
        if pend:
            self.pending_recovery = None
            self.stats["recoveries_executed"] = self.stats.get(
                "recoveries_executed", 0) + 1
            if pend["kind"] == "navigate":
                nav_command, nav_status = self._nav_to(obs, pend["target"])
                if nav_command:
                    forced = "explore"
            elif pend["kind"] == "skill":
                sk = pend["skill"]
                if sk == "explore" or check_preconditions(sk, obs)["ok"]:
                    forced = sk

        # 0. ANCHOR: если агент ушёл далеко от гивера при активном квесте,
        # принудительно возвращаемся.
        _giver_dist = ws.get("distance_to_giver", 999.0)
        _quest_active = (obs.get("quest") or {}).get("active", 0) > 0
        if _quest_active and isinstance(_giver_dist, (int, float)) and _giver_dist > 80:
            forced = "return_to_giver"
            print(f"[anchor] dist={_giver_dist:.1f} -> forced return_to_giver", flush=True)

        if forced is None and self.guard.is_looping():
            trip = self.guard.trip()
            self.stats["loops_tripped"] += 1
            forced = RECOVERY_TO_SKILL.get(trip["recovery_action"])
            self.last["loop"] = trip
        elif forced is None:
            self.last["loop"] = None
            sg_skill = (subgoal or {}).get("skill")
            kind = target_kind_for_subgoal(subgoal)
            if sg_skill:
                pre = check_preconditions(sg_skill, obs)
                if pre["ok"]:
                    forced = sg_skill
                else:
                    # Навык блокирован ТОЛЬКО дистанцией -> это работа
                    # навигации, а не повод бросить цель и уйти фармить
                    # (живой баг: subgoal ACCEPT, гивер 9 yd, агент ушёл).
                    dist_only = [f for f in pre["failed"]
                                 if f in DISTANCE_PRECONDITIONS]
                    if dist_only and len(dist_only) == len(pre["failed"]) and kind:
                        nav_command, nav_status = self._nav_to(
                            obs, kind, (subgoal or {}).get("target"))
                        if nav_command:
                            forced = "explore"
            # Подцель, у которой ЕСТЬ цель перемещения, обязана идти через
            # навигацию. Раньше условие смотрело на имя (GO_TO*/RETURN*), и
            # FIND_MOB с skill=explore проваливался мимо: у explore нет
            # предусловий -> forced=explore -> шаг на месте, pos не менялась
            # (живой замер: 8 шагов FIND_MOB, pos=(0,0), nav_commands=0).
            if kind and nav_command is None and (subgoal or {}).get("skill") == "explore":
                # Если моб УЖЕ в зоне видимости (nearby_mobs>0), НЕ форсируем
                # слепой explore — это уводило агента на 290yd от гивера
                # (живой замер: dist=267..290 при qs=ACTIVE). farm (scripted
                # chase) сам дойдёт до моба и добьёт его; оставляем выбор
                # политики. Explore оставляем только для РЕАЛЬНОГО поиска,
                # когда мобов нет в радиусе сканирования.
                _nearby_mobs = (obs.get("world") or {}).get("nearby_mobs", 0) or 0
                if _nearby_mobs <= 0:
                    nav_command, nav_status = self._nav_to(
                        obs, kind, (subgoal or {}).get("target"))
                    if nav_command:
                        forced = "explore"

        if forced and forced not in masked:
            # форсируем только исполнимое
            if forced == "explore" or check_preconditions(forced, obs)["ok"]:
                masked = [forced] + masked

        name = (subgoal or {}).get("subgoal") or "?"
        self.stats["subgoals"][name] = self.stats["subgoals"].get(name, 0) + 1

        # Build explicit decision context (replaces hidden hints channel)
        _nav_intent = None
        if nav_command:
            _nav_intent = (subgoal or {}).get("subgoal") or "EXPLORE"
        decision_ctx = DecisionContext(
            allowed_skills=tuple(masked),
            forced_skill=forced,
            subgoal=(subgoal or {}).get("subgoal"),
            navigation_intent=_nav_intent,
            target=(self.nav.target if self.nav else None),
            reason=(
                "recovery" if forced and self.last.get("loop")
                else "forced_skill" if forced
                else "subgoal" if forced
                else "policy"),
        )

        # TELEMETRY: log autonomy loop decision
        try:
            import json, os, time
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "autonomy_log.jsonl")
            entry = {
                "t": time.time(),
                "step": self.stats["steps"],
                "chooser": "autonomy_loop",
                "reason": decision_ctx.reason,
                "forced_skill": forced,
                "subgoal": (subgoal or {}).get("subgoal"),
                "allowed_skills": tuple(masked),
                "nav_command": nav_command,
                "nav_status": nav_status,
                "loop_detected": self.guard.is_looping(),
                "recovery_pending": self.pending_recovery,
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

        return {
            "candidates": masked,
            "subgoal": subgoal,
            "forced_skill": forced,
            "nav_command": nav_command,
            "nav_status": nav_status,
            "obs": obs,
            "blocked": self.guard.blocked_actions(),
            "decision_context": decision_ctx,
        }

    def _nav_to(self, obs, kind, hint=None):
        """Поставить цель навигации и вернуть (команда моста, статус)."""
        if not self.nav.set_target(obs, kind, hint):
            # Цели нужного типа в зоне видимости НЕТ. Для FIND_* это значит
            # «искать», а не «стоять»: без этого агент топчется на месте,
            # пока квестовый моб живёт в 200 ярдах (живой замер: FIND_MOB,
            # _entities без мобов, nav_command=None, 0 прогресса).
            cmd = self.nav.explore_command(obs)
            if cmd:
                self.stats["nav_explore"] = self.stats.get("nav_explore", 0) + 1
                return cmd, "SEARCHING"
            return None, "NO_TARGET"
        st = self.nav.observe(obs)
        self.nav_target_before = dict(self.nav.target or {})
        if st["status"] in ("ARRIVED",):
            self.stats["nav_arrived"] = self.stats.get("nav_arrived", 0) + 1
            return None, st["status"]
        if st["status"] in ("STUCK", "BLOCKED"):
            self.stats["nav_stuck"] = self.stats.get("nav_stuck", 0) + 1
        cmd = self.nav.nav_command()
        if cmd:
            self.stats["nav_commands"] = self.stats.get("nav_commands", 0) + 1
        return cmd, st["status"]

    # ----------------------------------------------------------- post-action
    def after_action(self, action: str, info_after: Dict[str, Any],
                     ws_after: Dict[str, Any],
                     reward: float = 0.0,
                     goal: Optional[str] = None,
                     world_mem=None) -> Dict[str, Any]:
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
            # P0.6: стратегия восстановления ИСПОЛНЯЕТСЯ, а не только пишется
            # в лог. Транслируем её в конкретное действие следующего шага.
            plan = plan_recovery(rec.get("recovery_action"))
            recovery["plan"] = plan
            if plan["kind"] == "control":
                op = plan["op"]
                if op == "abandon":
                    # P0.7: отказ реально блокирует цель на cooldown, иначе
                    # policy выбирает ту же самую и цикл повторяется
                    objective = self._objective_key(obs_before)
                    self.blacklist.abandon(objective, failure_reason)
                    self.stats["abandoned"] = self.stats.get("abandoned", 0) + 1
                    self.planner.force_replan()
                elif op in ("next", "replan"):
                    self.planner.force_replan()
                self.pending_recovery = None
            else:
                # навык или навигация — применим на следующем before_action
                self.pending_recovery = plan
        else:
            self.recovery.on_success(action)
            self.pending_recovery = None

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
