"""goal_fsm.py — Quest Goal Finite State Machine (persistent state tracker ONLY).

After STREAM J2 refactor:
  - FSM tracks quest state (QUEST_NONE -> DO_OBJECTIVE -> DONE, etc.)
  - FSM does NOT decide actions — that's ArbitrationLayer's job
  - FSM answers "what state am I in?" not "what should I do?"

Responsibilities:
  - update_from_world(): sync state with observed quest_status
  - set()/suggest(): record goal (single writer, advisory)
  - save()/load(): persist state across restarts
  - enter_dead()/resume_from_dead(): death recovery state

Removed (moved to ArbitrationLayer):
  - decide() and all _handle_*() methods
  - HP override (now in safety.py)
  - stuck detection (now in recovery_layer.py)
"""
from enum import Enum, auto
from typing import Optional, Dict, Any
import json
import os


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


# Константы
MIN_DWELL_STEPS = 5        # минимальное число шагов между сменами цели
INTERACT_RANGE = 7.0       # дистанция взаимодействия с NPC (из контрактов)
OBJECTIVE_PROXIMITY = 8.0  # дистанция для прогресса квеста

# Backward-compatible string constants for set()/suggest() goal args.
# Tests and external code import these as module-level names.
NO_QUEST = "NO_QUEST"
FIND_GIVER = "FIND_GIVER"
ACCEPT = "ACCEPT"
VERIFY_ACCEPT = "VERIFY_ACCEPT"
DO_OBJECTIVE = "DO_OBJECTIVE"
VERIFY_PROGRESS = "VERIFY_PROGRESS"
RETURN_TO_GIVER = "RETURN_TO_GIVER"
TURN_IN = "TURN_IN"
VERIFY_TURN_IN = "VERIFY_TURN_IN"
RESPAWN = "RESPAWN"
DONE = "DONE"
ERROR = "ERROR"
HEAL = "HEAL"
SELL_REPAIR = "SELL_REPAIR"


class GoalFSM:
    """Конечный автомат выполнения квестов — ТОЛЬКО отслеживание состояния.

    Does NOT decide actions. Does NOT contain if/elif for skill selection.
    ArbitrationLayer reads fsm.goal / fsm.state for telemetry and logging.
    """

    def __init__(self, memory_path: Optional[str] = None, path: Optional[str] = None):
        self.state = QuestState.QUEST_NONE
        self.active_quest: Optional[Dict] = None
        self.quest_giver: Optional[Dict] = None
        self.failure_reason = FailureReason.NONE
        self.failure_count: Dict[FailureReason, int] = {}
        # Сохраняем квест/гивера перед смертью для восстановления после респауна
        self._pre_death_quest: Optional[Dict] = None
        self._pre_death_giver: Optional[Dict] = None
        self.step_count = 0
        self.total_kills = 0
        self.total_deaths = 0
        self.total_xp = 0
        self.total_copper = 0
        self.last_suggestion: Optional[str] = None
        self.last_suggestion_reason: Optional[str] = None
        self.goal_source: Optional[str] = None
        self.switch_count: int = 0
        self._last_set_step: int = 0
        self._goal_str: Optional[str] = None
        # Backward compat: path= alias for memory_path (old tests use path=)
        self.memory_path = memory_path or path or os.path.join(
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
            "active_quest": self.active_quest,
            "quest_giver": self.quest_giver,
        }
        try:
            with open(self.memory_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    @property
    def phase(self) -> Optional[str]:
        """Current quest phase (without quest_id suffix).

        Returns the QuestState name for use by the arbitration layer.
        Examples: "QUEST_NONE", "DO_OBJECTIVE", "RETURN_TO_GIVER", "DONE".
        """
        if self.state == QuestState.QUEST_NONE:
            return "QUEST_NONE"
        if self.state == QuestState.DONE:
            return "DONE"
        return self.state.name

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
            # Use _goal_str if set (handles non-QuestState goals like SELL_REPAIR, HEAL)
            goal_name = self._goal_str if self._goal_str else self.state.name
            return f"{goal_name}:{self.active_quest.get('id', '?')}"
        return self.state.name

    def resume_after_respawn(self):
        """Агент воскрес — сохраняем квест и гивер."""
        if self.active_quest:
            self.state = QuestState.RETURN_TO_GIVER
            self._log_transition(QuestState.RESPAWN, QuestState.RETURN_TO_GIVER, "respawn_resume_quest")
        else:
            self.state = QuestState.QUEST_NONE
            self._log_transition(QuestState.RESPAWN, QuestState.QUEST_NONE, "respawn_no_quest")

    def enter_dead(self):
        """Агент умер — переводим FSM в RESPAWN, сохраняя квест."""
        if self.state != QuestState.RESPAWN:
            self.total_deaths += 1
            self._record_failure(FailureReason.COMBAT_FAILURE)
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
        has_ready = world_state.get("has_ready", False)
        old_state = self.state
        if quest_status == "ACTIVE" and self.state in (
            QuestState.QUEST_NONE, QuestState.FIND_GIVER, QuestState.ACCEPT,
            QuestState.VERIFY_ACCEPT, QuestState.ERROR,
            QuestState.TURN_IN, QuestState.VERIFY_TURN_IN,
        ):
            # Fix5 regression: TURN_IN/VERIFY_TURN_IN against an incomplete quest
            # is stale — demote back to DO_OBJECTIVE.
            self.state = QuestState.DO_OBJECTIVE
        elif quest_status == "ACTIVE" and self.state == QuestState.RETURN_TO_GIVER:
            # RETURN_TO_GIVER against ACTIVE quest: demote ONLY if no ready quest.
            # If has_ready=True, the quest is truly ready and we should stay.
            if not has_ready:
                self.state = QuestState.DO_OBJECTIVE
        elif quest_status == "READY_TO_TURN_IN" and self.state in (
            QuestState.DO_OBJECTIVE, QuestState.VERIFY_PROGRESS,
            QuestState.FIND_GIVER, QuestState.ERROR, QuestState.QUEST_NONE
        ):
            self.state = QuestState.RETURN_TO_GIVER
        elif quest_status == "DONE" and self.state != QuestState.DONE:
            self.state = QuestState.DONE
        elif quest_status == "NONE" and self.state in (
            QuestState.DONE, QuestState.ERROR, QuestState.TURN_IN,
            QuestState.VERIFY_TURN_IN, QuestState.RETURN_TO_GIVER,
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

    def suggest(self, goal: str, reason: str = "") -> bool:
        """Запомнить совет от LLM/политики. НЕ меняет цель FSM.

        Возврат False означает «цель не менялась» (совместимость с apply_decision).
        """
        self.last_suggestion = goal
        self.last_suggestion_reason = reason
        return False

    def set(self, goal: str, quest_id: str, source: str = "fsm",
            step: int = 0, force: bool = False) -> bool:
        """Установить цель FSM. Возврат True означает «цель изменилась».

        Контракт:
        - Записи той же цели НЕ увеличивают switch_count.
        - Легитимная смена не чаще, чем раз в MIN_DWELL_STEPS шагов
          (кроме force=True — смерть/критический HP).
        """
        if goal == self._goal_str:
            return False
        if not force and step - self._last_set_step < MIN_DWELL_STEPS:
            return False
        # Map goal string to QuestState and set it
        try:
            new_state = QuestState[goal]
            self.state = new_state
        except KeyError:
            # Non-QuestState goals (SELL_REPAIR, HEAL, etc.) — keep current state
            # but record the goal string for telemetry
            pass
        self.active_quest = {"id": quest_id}
        self._goal_str = goal
        self.goal_source = source
        self._last_set_step = step
        self.switch_count += 1
        return True

    def _record_failure(self, reason: FailureReason):
        """Записывает причину неудачи для анализа."""
        self.failure_count[reason] = self.failure_count.get(reason, 0) + 1
        self.save()

    def _log_transition(self, from_state: QuestState, to_state: QuestState, reason: str = ""):
        """Логирует переход между состояниях (P0: телеметрия)."""
        import logging
        logger = logging.getLogger(__name__)
        msg = f"FSM: {from_state.name} -> {to_state.name}"
        if reason:
            msg += f" ({reason})"
        logger.info(msg)

    def get_diagnostics(self) -> Dict:
        """Возвращает диагностическую информацию."""
        return {
            "state": self.state.name,
            "failure_reason": self.failure_reason.name,
            "failure_count": {k.name: v for k, v in self.failure_count.items()},
            "step_count": self.step_count,
        }
