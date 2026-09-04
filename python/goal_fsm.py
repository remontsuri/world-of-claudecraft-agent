"""goal_fsm.py — Quest Goal Finite State Machine.

Явная машина состояний для выполнения квестов. Заменяет скрытый
policy hints детерминированным потоком с верификацией на каждом переходе.

Состояния:
  QUEST_NONE → FIND_GIVER → ACCEPT → VERIFY_ACCEPT → DO_OBJECTIVE →
  VERIFY_PROGRESS → RETURN_TO_GIVER → TURN_IN → VERIFY_TURN_IN → DONE

Каждый переход верифицируется через объективные проверки.
Неудача переводит в соответствующее состояние ошибки с анализом причины.
"""

from enum import Enum, auto
from typing import Optional, Tuple, Dict, Any
import math
import json
import os

# Константы
INTERACT_RANGE = 7.0       # дистанция взаимодействия с NPC (из контрактов)
OBJECTIVE_PROXIMITY = 8.0  # дистанция для прогресса квеста
STUCK_THRESHOLD = 10       # шагов без прогресса = застревание


class QuestState(Enum):
    """Состояния квестового FSM."""
    QUEST_NONE = auto()
    FIND_GIVER = auto()
    ACCEPT = auto()
    VERIFY_ACCEPT = auto()
    DO_OBJECTIVE = auto()
    VERIFY_PROGRESS = auto()
    RETURN_TO_GIVER = auto()
    TURN_IN = auto()
    VERIFY_TURN_IN = auto()
    RESPAWN = auto()          # Обработка смерти и респаун
    DONE = auto()
    ERROR = auto()


class FailureReason(Enum):
    """Причины неудач для анализа и восстановления."""
    NONE = auto()
    NAVIGATION_FAILURE = auto()      # не удалось дойти до цели
    COMBAT_FAILURE = auto()          # смерть в бою
    QUEST_STATE_FAILURE = auto()     # квест не в ожидаемом состоянии
    INTERACTION_FAILURE = auto()     # не удалось взаимодействовать
    SURVIVAL_FAILURE = auto()        # hp критический
    ENVIRONMENT_FAILURE = auto()     # мир не загружен / ошибка среды
    STUCK_FAILURE = auto()           # застревание (нет прогресса N шагов)


class GoalFSM:
    """Конечный автомат выполнения квестов."""

    def __init__(self, memory_path: Optional[str] = None):
        self.state = QuestState.QUEST_NONE
        self.active_quest: Optional[Dict] = None
        self.quest_giver: Optional[Dict] = None
        self.failure_reason = FailureReason.NONE
        self.failure_count: Dict[FailureReason, int] = {}
        # Сохраняем квест/гивера перед смертью для восстановления после респауна
        self._pre_death_quest: Optional[Dict] = None
        self._pre_death_giver: Optional[Dict] = None
        self.world_mem = None  # WorldMemory для доступа к giver_pos
        self.navigation_memory: Dict[str, Any] = {
            "last_positions": [],
            "last_distances": [],
            "best_distance": float("inf"),
            "no_progress_steps": 0,
            "stuck_detected": False
        }
        self.step_count = 0
        self.total_kills = 0
        self.total_deaths = 0
        self.total_xp = 0
        self.total_copper = 0
        self.memory_path = memory_path or os.path.join(
            os.path.dirname(__file__), "goal_fsm_state.json"
        )
        self._load()

    def _load(self):
        """Восстановление состояния из файла."""
        if not os.path.exists(self.memory_path):
            return
        try:
            with open(self.memory_path, "r") as f:
                data = json.load(f)
            state_name = data.get("state")
            if state_name:
                try:
                    self.state = QuestState[state_name]
                except KeyError:
                    self.state = QuestState.QUEST_NONE
            self.failure_count = {
                FailureReason[k]: v
                for k, v in data.get("failure_count", {}).items()
            }
            self.total_kills = data.get("total_kills", 0)
            self.total_deaths = data.get("total_deaths", 0)
            self.total_xp = data.get("total_xp", 0)
            self.total_copper = data.get("total_copper", 0)
            # 2026-09-03 FIX: восстанавливаем active_quest и quest_giver
            self.active_quest = data.get("active_quest")
            self.quest_giver = data.get("quest_giver")
        except Exception:
            pass

    def save(self):
        """Сохранение состояния."""
        data = {
            "state": self.state.name,
            "failure_count": {k.name: v for k, v in self.failure_count.items()},
            "total_kills": self.total_kills,
            "total_deaths": self.total_deaths,
            "total_xp": self.total_xp,
            "total_copper": self.total_copper,
            "step_count": self.step_count,
            # 2026-09-03 FIX: сохраняем active_quest и quest_giver для
            # восстановления после рестарта. Без этого FSM загружается с
            # state=RETURN_TO_GIVER, но quest_giver=None → сбрасывается в QUEST_NONE.
            "active_quest": self.active_quest,
            "quest_giver": self.quest_giver,
        }
        try:
            with open(self.memory_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    @property
    def quest_id(self) -> Optional[str]:
        """ID текущего квеста."""
        if self.active_quest:
            return str(self.active_quest.get("id", "?"))
        return None

    @property
    def goal(self) -> Optional[str]:
        """Текущая цель FSM для логирования."""
        if self.state == QuestState.QUEST_NONE:
            return None
        if self.state == QuestState.DONE:
            return "QUEST_COMPLETE"
        if self.active_quest:
            return f"{self.state.name}:{self.active_quest.get('id', '?')}"
        return self.state.name

    def resume_after_respawn(self):
        """Агент воскрес — сохраняем квест и гивер."""
        # Не сбрасываем FSM! Агент должен продолжить текущий квест
        if self.active_quest:
            self.state = QuestState.RETURN_TO_GIVER
            self._log_transition(QuestState.RESPAWN, QuestState.RETURN_TO_GIVER, "respawn_resume_quest")
        else:
            self.state = QuestState.QUEST_NONE
            self._log_transition(QuestState.RESPAWN, QuestState.QUEST_NONE, "respawn_no_quest")

    def enter_dead(self):
        """Агент умер — переводим FSM в RESPAWN, сохраняя квест."""
        if self.state != QuestState.RESPAWN:
            self._record_failure(FailureReason.COMBAT_FAILURE)
            # Сохраняем состояние для восстановления
            self._pre_death_quest = self.active_quest
            self._pre_death_giver = self.quest_giver
            old_state = self.state
            self.state = QuestState.RESPAWN
            self.failure_reason = FailureReason.COMBAT_FAILURE
            self._log_transition(old_state, QuestState.RESPAWN, "death")

    def resume_from_dead(self):
        """Агент воскрес — восстанавливаем квест."""
        if self._pre_death_quest:
            self.active_quest = self._pre_death_quest
            self.quest_giver = self._pre_death_giver
            self.state = QuestState.RETURN_TO_GIVER
            self.failure_reason = FailureReason.NONE
            self._log_transition(QuestState.RESPAWN, QuestState.RETURN_TO_GIVER, "respawn_restore_quest")
        else:
            self.state = QuestState.QUEST_NONE
            self._log_transition(QuestState.RESPAWN, QuestState.QUEST_NONE, "respawn_no_quest")

    def update_from_world(self, world_state: dict):
        """Синхронизирует состояние FSM с наблюдаемым миром.
        
        Вызывается в начале каждого шага. Если квест активен — переводит в 
        DO_OBJECTIVE. Если квест завершён — в DONE.
        """
        quest_status = world_state.get("quest_status", "NONE")
        old_state = self.state
        if quest_status == "ACTIVE" and self.state in (
            QuestState.QUEST_NONE, QuestState.FIND_GIVER, QuestState.ACCEPT,
            QuestState.VERIFY_ACCEPT, QuestState.ERROR
        ):
            self.state = QuestState.DO_OBJECTIVE
        elif quest_status == "READY_TO_TURN_IN" and self.state in (
            QuestState.DO_OBJECTIVE, QuestState.VERIFY_PROGRESS,
            QuestState.FIND_GIVER, QuestState.ERROR, QuestState.QUEST_NONE
        ):
            self.state = QuestState.RETURN_TO_GIVER
        elif quest_status == "DONE" and self.state != QuestState.DONE:
            self.state = QuestState.DONE
        elif quest_status == "NONE" and self.state in (
            QuestState.DONE, QuestState.ERROR
        ):
            self.reset()
        if old_state != self.state:
            print(f"[fsm] {old_state.name} -> {self.state.name} (qs={quest_status})", flush=True)

    def reset(self):
        """Сброс для нового квеста."""
        self.state = QuestState.QUEST_NONE
        self.active_quest = None
        self.quest_giver = None
        self.failure_reason = FailureReason.NONE
        self.navigation_memory = {
            "last_positions": [],
            "last_distances": [],
            "best_distance": float("inf"),
            "no_progress_steps": 0,
            "stuck_detected": False
        }

    # ---- Основной цикл ----

    def decide(self, world_state: dict, info: dict) -> Tuple[str, Dict]:
        """Принимает решение на основе состояния FSM.

        Returns:
            (action_name, ctx) — действие для Skill Layer
        """
        self.step_count += 1

        # Обновляем навигационную память
        self._update_navigation_memory(world_state, info)

        # Проверяем критический HP — приоритет выживания
        if world_state.get("hp_frac", 1.0) < 0.2:
            return "heal", {"reason": "critical_hp"}

        # Проверяем застревание
        if self._detect_stuck():
            return self._handle_stuck(world_state, info)

        # Сброс из ERROR при наличии активного квеста
        if self.state == QuestState.ERROR:
            if self.active_quest:
                self.state = QuestState.DO_OBJECTIVE
            else:
                self.state = QuestState.QUEST_NONE

        # Основная логика по состоянию
        handler = {
            QuestState.QUEST_NONE: self._handle_quest_none,
            QuestState.FIND_GIVER: self._handle_find_giver,
            QuestState.ACCEPT: self._handle_accept,
            QuestState.VERIFY_ACCEPT: self._handle_verify_accept,
            QuestState.DO_OBJECTIVE: self._handle_do_objective,
            QuestState.VERIFY_PROGRESS: self._handle_verify_progress,
            QuestState.RETURN_TO_GIVER: self._handle_return_to_giver,
            QuestState.TURN_IN: self._handle_turn_in,
            QuestState.VERIFY_TURN_IN: self._handle_verify_turn_in,
            QuestState.RESPAWN: self._handle_respawn,
            QuestState.DONE: self._handle_done,
        }

        handler_fn = handler.get(self.state, self._handle_quest_none)
        return handler_fn(world_state, info)

    def _handle_quest_none(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Нет активного квеста — ищем квестгивера."""
        nearby = info.get("nearby", []) or []
        quest_npcs = [
            e for e in nearby
            if (e.get("kind") == "npc" or e.get("type") == "npc")
            and (e.get("questIds") or e.get("questId"))
        ]
        if quest_npcs:
            quest_npcs.sort(key=lambda n: n.get("dist", float("inf")))
            self.quest_giver = quest_npcs[0]
            self.state = QuestState.FIND_GIVER
            return self._handle_find_giver(ws, info)
        # Нет квестгивера рядом — исследуем
        return "explore", {"reason": "no_quest_giver"}

    def _handle_find_giver(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Идём к квестгиверу, взаимодействуем для получения квеста."""
        # Если гивер не запомнен — ищем NPC в nearby
        if not self.quest_giver:
            nearby = info.get("nearby", []) or []
            quest_npcs = [
                e for e in nearby
                if (e.get("kind") == "npc" or e.get("type") == "npc")
                and (e.get("questIds") or e.get("questId"))
            ]
            if quest_npcs:
                quest_npcs.sort(key=lambda n: n.get("dist", float("inf")))
                self.quest_giver = quest_npcs[0]
            else:
                # Нет NPC рядом — исследуем
                return "explore", {"reason": "no_giver_nearby"}

        if not self.quest_giver:
            self.state = QuestState.QUEST_NONE
            return "explore", {"reason": "no_giver"}

        dist = self.quest_giver.get("dist", float("inf"))
        if dist is None:
            dist = self._calc_dist_to_giver(info)

        if dist <= INTERACT_RANGE:
            self.state = QuestState.ACCEPT
            return "accept_quest", {"npc": self.quest_giver}
        else:
            return "navigate", {
                "target": self.quest_giver,
                "reason": "approaching_giver"
            }

    def _handle_accept(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Принимаем квест."""
        if self.quest_giver:
            self.state = QuestState.VERIFY_ACCEPT
            return "accept_quest", {"npc": self.quest_giver}
        self.state = QuestState.QUEST_NONE
        return "explore", {"reason": "no_giver"}

    def _handle_verify_accept(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Верифицируем, что квест принят."""
        quest_status = ws.get("quest_status", "NONE")
        if quest_status == "ACTIVE":
            self.state = QuestState.DO_OBJECTIVE
            # Известим DO_OBJECTIVE с пустым контекстом
            return self._handle_do_objective(ws, info)
        # Не принят — пробуем снова
        self.failure_reason = FailureReason.QUEST_STATE_FAILURE
        self._record_failure(FailureReason.QUEST_STATE_FAILURE)
        self.state = QuestState.ACCEPT
        return "accept_quest", {"npc": self.quest_giver}

    def _handle_do_objective(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Выполняем объектив квеста (фарм, лут, сбор)."""
        quest_status = ws.get("quest_status", "NONE")
        if quest_status == "READY_TO_TURN_IN":
            self.state = QuestState.RETURN_TO_GIVER
            return self._handle_return_to_giver(ws, info)
        if quest_status != "ACTIVE":
            self.state = QuestState.ERROR
            return "explore", {"reason": "quest_not_active"}

        # Есть мобы — фармим
        has_mob = ws.get("has_mob", False)
        if has_mob:
            return "farm", {"reason": "objective_mob"}

        # Нет целей — исследуем
        return "explore", {"reason": "no_objective_target"}

    def _handle_verify_progress(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Проверяем прогресс квеста."""
        quest_status = ws.get("quest_status", "NONE")
        if quest_status == "READY_TO_TURN_IN":
            self.state = QuestState.RETURN_TO_GIVER
            return self._handle_return_to_giver(ws, info)
        if quest_status == "ACTIVE":
            self.state = QuestState.DO_OBJECTIVE
            return self._handle_do_objective(ws, info)
        self.state = QuestState.ERROR
        return "explore", {"reason": "quest_state_unknown"}

    def _handle_return_to_giver(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Возвращаемся к квестгиверу для сдачи."""
        if not self.quest_giver:
            # 2026-09-03 FIX: fallback на world_mem.giver_pos() перед сбросом.
            # Раньше quest_giver=None сразу сбрасывал FSM в QUEST_NONE, теряя
            # прогресс квеста. Теперь пытаемся восстановить гивера из памяти.
            qid = self.active_quest.get("id") if self.active_quest else None
            if qid and self.world_mem is not None:
                pos = self.world_mem.giver_pos(qid)
                if pos and pos.get("x") is not None:
                    self.quest_giver = pos
                    print(f"[fsm] quest_giver restored from world_mem: {qid}@{pos['x']:.0f},{pos['z']:.0f}", flush=True)
            if not self.quest_giver:
                # 2026-09-03 FIX: scan nearby NPCs for giver as last resort.
                # After FSM load, active_quest and quest_giver may be None,
                # but the game still has the quest active. Scan nearby NPCs
                # for one that offers/owns this quest.
                for e in ((info or {}).get("nearby") or []):
                    ids = e.get("questIds") or []
                    # If we have an active quest, match by ID; otherwise take any quest NPC
                    if (qid and qid in ids) or (not qid and ids):
                        self.quest_giver = {"x": e.get("x"), "z": e.get("z"), "id": e.get("id")}
                        print(f"[fsm] quest_giver restored from nearby: {self.quest_giver}", flush=True)
                        break
            if not self.quest_giver:
                self.state = QuestState.QUEST_NONE
                return "explore", {"reason": "no_giver"}

        dist = self._calc_dist_to_giver(info)
        if dist <= INTERACT_RANGE:
            self.state = QuestState.TURN_IN
            return "turn_in_quest", {"npc": self.quest_giver}
        return "navigate", {
            "target": self.quest_giver,
            "reason": "returning_to_giver"
        }

    def _handle_turn_in(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Сдаём квест."""
        if self.quest_giver:
            self.state = QuestState.VERIFY_TURN_IN
            return "turn_in_quest", {"npc": self.quest_giver}
        self.state = QuestState.QUEST_NONE
        return "explore", {"reason": "no_giver"}

    def _handle_verify_turn_in(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Верифицируем сдачу квеста."""
        quest_status = ws.get("quest_status", "NONE")
        if quest_status == "DONE":
            self.state = QuestState.DONE
            return "explore", {"reason": "quest_complete"}
        # Не сдан — проверяем READY
        if quest_status == "READY_TO_TURN_IN":
            self.state = QuestState.TURN_IN
            return "turn_in_quest", {"npc": self.quest_giver}
        # Неизвестное состояние
        self.failure_reason = FailureReason.QUEST_STATE_FAILURE
        self._record_failure(FailureReason.QUEST_STATE_FAILURE)
        self.state = QuestState.RETURN_TO_GIVER
        return "explore", {"reason": "turn_in_failed"}

    def _handle_done(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Квест завершён — ищем следующий."""
        self.reset()
        return "explore", {"reason": "quest_done_search_next"}

    def _handle_respawn(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Обработка смерти — ожидание возрождения."""
        player = info.get("player", {}) or {}
        dead = player.get("dead", False)
        hp = player.get("hp", 0)
        if not dead and hp > 0:
            self.state = QuestState.QUEST_NONE
            self.failure_reason = FailureReason.NONE
            return "explore", {"reason": "respawn_recovered"}
        return "heal", {"reason": "awaiting_respawn"}

    # ---- Навигационная память и обнаружение застревания ----

    def _update_navigation_memory(self, ws: dict, info: dict):
        """Обновляет историю позиций и дистанций."""
        pos = ws.get("player_pos") or info.get("player_pos")
        if pos and len(pos) >= 2:
            self.navigation_memory["last_positions"].append((pos[0], pos[2]))
            if len(self.navigation_memory["last_positions"]) > 50:
                self.navigation_memory["last_positions"] = self.navigation_memory["last_positions"][-50:]

        dist = ws.get("distance_to_giver")
        if dist is not None:
            self.navigation_memory["last_distances"].append(dist)
            if len(self.navigation_memory["last_distances"]) > 50:
                self.navigation_memory["last_distances"] = self.navigation_memory["last_distances"][-50:]

            if dist < self.navigation_memory["best_distance"]:
                self.navigation_memory["best_distance"] = dist
                self.navigation_memory["no_progress_steps"] = 0
            else:
                self.navigation_memory["no_progress_steps"] += 1

        # Если distance_to_giver не обновляется (999), используем WorldMemory
        if ws.get("distance_to_giver", 999) >= 999 and hasattr(self, "world_mem") and self.world_mem:
            giver_pos = self.world_mem.giver_pos(
                ws.get("quest", {}).get("id") if ws.get("quest") else None
            )
            if giver_pos and giver_pos.get("x") is not None:
                ppos = info.get("player_pos") or [0, 0]
                alt_dist = ((giver_pos["x"] - ppos[0]) ** 2 + (giver_pos["z"] - ppos[1]) ** 2) ** 0.5
                if alt_dist < self.navigation_memory["best_distance"]:
                    self.navigation_memory["best_distance"] = alt_dist
                    self.navigation_memory["no_progress_steps"] = 0
                else:
                    self.navigation_memory["no_progress_steps"] += 1

    def _detect_stuck(self) -> bool:
        """Определяет, застрял ли агент."""
        return self.navigation_memory["no_progress_steps"] >= STUCK_THRESHOLD

    def _handle_stuck(self, ws: dict, info: dict) -> Tuple[str, Dict]:
        """Реакция на застревание — смена стратегии."""
        self.navigation_memory["stuck_detected"] = True
        self._record_failure(FailureReason.STUCK_FAILURE)
        # Сброс счётчика для следующей итерации
        self.navigation_memory["no_progress_steps"] = 0
        return "explore", {"reason": "unstick"}

    def _record_failure(self, reason: FailureReason):
        """Записывает причину неудачи для анализа."""
        self.failure_count[reason] = self.failure_count.get(reason, 0) + 1
        self.save()

    def _log_transition(self, from_state: QuestState, to_state: QuestState, reason: str = ""):
        """Логирует переход между состояниями (P0: телеметрия)."""
        import logging
        logger = logging.getLogger(__name__)
        msg = f"FSM: {from_state.name} -> {to_state.name}"
        if reason:
            msg += f" ({reason})"
        logger.info(msg)

    def _calc_dist_to_giver(self, info: dict) -> Optional[float]:
        """Вычисляет расстояние до квестгивера, используя WorldMemory если нужно."""
        if not self.quest_giver:
            return None
        gx, gz = self.quest_giver.get("x"), self.quest_giver.get("z")
        if gx is None or gz is None:
            return None
        ppos = info.get("player_pos") or [0, 0]
        return math.sqrt((gx - ppos[0]) ** 2 + (gz - ppos[1]) ** 2)

    def get_diagnostics(self) -> Dict:
        """Возвращает диагностическую информацию."""
        return {
            "state": self.state.name,
            "failure_reason": self.failure_reason.name,
            "failure_count": {k.name: v for k, v in self.failure_count.items()},
            "navigation_memory": {
                "last_positions_count": len(self.navigation_memory["last_positions"]),
                "best_distance": self.navigation_memory["best_distance"],
                "no_progress_steps": self.navigation_memory["no_progress_steps"],
                "stuck_detected": self.navigation_memory["stuck_detected"],
            },
            "step_count": self.step_count,
        }
