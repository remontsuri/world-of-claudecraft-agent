"""Quest Truth Layer — абсолютная истина о состоянии квестов (этап 1, пункт 1).

Зачем (требование пользователя 2026-08-24): «квест уже взят → агент снова
пытается взять квест у NPC» должно стать ФИЗИЧЕСКИ невозможным. Раньше каждый
слой (policy, FSM, brain, skills) выводил состояние квеста сам, по-своему
читая снапшот — отсюда рассогласование и бессмысленные действия.

Теперь состояние квеста выводится в ОДНОМ месте. Все остальные читают отсюда.

Фаза выводится из наблюдаемых фактов сервера, а не из наших предположений:
  нет в логе                      -> AVAILABLE
  в done                          -> DONE
  в ready                         -> TURN_IN
  в active, цели не выполнены     -> COMPLETE_OBJECTIVE
  в active, цели выполнены        -> RETURN_TO_GIVER
Сервер иногда держит квест в active даже с выполненными целями — поэтому
RETURN_TO_GIVER отделён от TURN_IN.
"""
import math

# закрытый enum фаз: Goal Manager не должен получать мусор
PHASES = ("AVAILABLE", "COMPLETE_OBJECTIVE", "RETURN_TO_GIVER", "TURN_IN", "DONE")

# сервер отклоняет turn_in дальше этой дистанции (INTERACT_RANGE + запас)
INTERACT_RANGE = 7.0


def _objectives_done(q: dict) -> bool:
    objs = q.get("objectives") or []
    if not objs:
        return False
    return all((o.get("current") or 0) >= (o.get("required") or 0) for o in objs)


def _progress_of(q: dict):
    cur = req = 0
    for o in (q.get("objectives") or []):
        cur += min(o.get("current") or 0, o.get("required") or 0)
        req += o.get("required") or 0
    return cur, req


class QuestTruth:
    """Неизменяемый снимок истины о квестах на один шаг."""

    def __init__(self, info: dict):
        self.info = info or {}
        quests = self.info.get("quests") or {}
        self._active = {q.get("id"): q for q in (quests.get("active") or []) if q.get("id")}
        self._ready = {q.get("id"): q for q in (quests.get("ready") or []) if q.get("id")}
        self._done = {q.get("id") for q in (quests.get("done") or []) if q.get("id")}
        pos = self.info.get("player_pos") or [0.0, 0.0]
        self._px, self._pz = float(pos[0]), float(pos[1])

    # ---- факты ----

    def phase(self, quest_id: str) -> str:
        if quest_id in self._done:
            return "DONE"
        if quest_id in self._ready:
            return "TURN_IN"
        q = self._active.get(quest_id)
        if q is None:
            return "AVAILABLE"
        return "RETURN_TO_GIVER" if _objectives_done(q) else "COMPLETE_OBJECTIVE"

    def progress(self, quest_id: str):
        q = self._active.get(quest_id) or self._ready.get(quest_id)
        return _progress_of(q) if q else (0, 0)

    def giver_pos(self, quest_id: str):
        q = self._active.get(quest_id) or self._ready.get(quest_id)
        npc = (q or {}).get("turnInNpc") or {}
        if npc.get("x") is None:
            return None
        return [float(npc["x"]), float(npc["z"])]

    def giver_distance(self, quest_id: str):
        pos = self.giver_pos(quest_id)
        if pos is None:
            return None
        return round(math.hypot(pos[0] - self._px, pos[1] - self._pz), 3)

    # ---- разрешения (то, ради чего слой существует) ----

    def can_accept(self, quest_id: str) -> bool:
        """ACCEPT законен ТОЛЬКО для квеста, которого нет в логе."""
        return self.phase(quest_id) == "AVAILABLE"

    def can_turn_in(self, quest_id: str) -> bool:
        """TURN_IN законен только в фазе TURN_IN и в радиусе взаимодействия.
        Дальше сервер отклоняет молча — не тратим шаг."""
        if self.phase(quest_id) != "TURN_IN":
            return False
        d = self.giver_distance(quest_id)
        return d is not None and d <= INTERACT_RANGE

    # ---- выбор ОДНОЙ активной цели ----

    def pick_target(self):
        """Готовый к сдаче важнее; иначе — ближайший к завершению активный."""
        if self._ready:
            return sorted(self._ready.keys())[0] if len(self._ready) == 1 else \
                min(self._ready.keys(), key=lambda k: -_progress_of(self._ready[k])[0])
        if not self._active:
            return None

        def remaining(qid):
            cur, req = _progress_of(self._active[qid])
            return (req - cur) if req else 999
        return min(self._active.keys(), key=remaining)
