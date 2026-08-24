"""Event Bus — события мира из дельты снапшотов (этап 1, пункт 2).

Зачем (ТЗ пользователя): «reward будет привязан к реальным событиям, а не к
догадке по snapshot». Раньше обучение видело только (state, action, reward) и
не знало, ЧТО именно произошло: прогресс квеста, смерть, застревание.

Контракты детекции согласованы с со-архитектором (раунд 4, Q10). Ключевые
защиты от ложных срабатываний:
  * ObjectiveProgress — только МОНОТОННЫЙ рост, подтверждённый 2 снапшотами
    (сервер при ресинке роняет счётчик вниз и возвращает обратно);
  * PlayerRespawned — обязательно предусловие смерти + полный hp + позиция
    у точки спавна, иначе обычный хил выглядел бы как воскрешение;
  * QuestCompleted — исчезновение из лога И рост глобального счётчика
    (одно исчезновение = ресинк, не завершение);
  * NavigationStuck — история из 8 кадров без движения, не одна пара.
"""
import math

STABILITY_FRAMES = 2        # подтверждение прогресса
STUCK_FRAMES = 8            # кадров без движения для NavigationStuck
STUCK_EPS = 0.5             # порог «не сдвинулся» (yd)
SPAWN_RADIUS = 5.0          # радиус точки спавна для дискриминатора respawn


def _q_progress(info: dict):
    """quest_id -> суммарный прогресс по активным и готовым квестам."""
    out = {}
    quests = info.get("quests") or {}
    for bucket in ("active", "ready"):
        for q in (quests.get(bucket) or []):
            qid = q.get("id")
            if not qid:
                continue
            cur = sum(min(o.get("current") or 0, o.get("required") or 0)
                      for o in (q.get("objectives") or []))
            out[qid] = cur
    return out


def _q_ids(info: dict):
    quests = info.get("quests") or {}
    ids = set()
    for bucket in ("active", "ready"):
        for q in (quests.get(bucket) or []):
            if q.get("id"):
                ids.add(q["id"])
    return ids


def _inv_ids(info: dict):
    return [s.get("itemId") for s in (info.get("inventory") or []) if s and s.get("itemId")]


class EventBus:
    def __init__(self, spawn_points=None):
        self.prev = None
        self.spawn_points = [list(p) for p in (spawn_points or [])]
        self._pending_progress = {}     # qid -> (candidate_value, frames_seen)
        self._base_progress = {}        # qid -> подтверждённое значение
        self._death_pending = False     # была смерть, ждём воскрешения
        self._still_frames = 0
        self._stuck_emitted = False

    # ---- вспомогательное ----

    def _near_spawn(self, pos) -> bool:
        for sp in self.spawn_points:
            if math.hypot(pos[0] - sp[0], pos[1] - sp[1]) <= SPAWN_RADIUS:
                return True
        return False

    # ---- главный вход ----

    def observe(self, info: dict):
        """Принять снапшот, вернуть список событий (может быть пустым)."""
        events = []
        if not isinstance(info, dict):
            return events
        prev = self.prev
        pos = info.get("player_pos") or [0.0, 0.0]
        player = info.get("player") or {}
        hp = player.get("hp")
        max_hp = player.get("maxHp") or 1
        deaths = info.get("deaths") or 0
        qdone = info.get("quests_done") or 0

        if prev is None:
            self.prev = info
            self._base_progress = _q_progress(info)
            return events

        pplayer = prev.get("player") or {}
        php = pplayer.get("hp")
        pdeaths = prev.get("deaths") or 0
        pqdone = prev.get("quests_done") or 0
        ppos = prev.get("player_pos") or [0.0, 0.0]

        # --- смерть ---
        died = (deaths > pdeaths) or (php is not None and hp is not None
                                      and php > 0 and hp == 0)
        if died:
            events.append({"type": "PlayerDied", "deaths": deaths})
            self._death_pending = True

        # --- воскрешение: нужны ВСЕ три признака ---
        if (self._death_pending and not died and hp is not None
                and hp >= max_hp and self._near_spawn(pos)):
            events.append({"type": "PlayerRespawned", "pos": list(pos)})
            self._death_pending = False

        # --- урон (но не прыжок hp при воскрешении) ---
        if (not died and php is not None and hp is not None and hp < php
                and not (hp >= max_hp)):
            events.append({"type": "DamageTaken", "amount": php - hp})

        # --- квесты: принятие и завершение ---
        ids_before, ids_after = _q_ids(prev), _q_ids(info)
        for qid in sorted(ids_after - ids_before):
            events.append({"type": "QuestAccepted", "quest_id": qid})
        for qid in sorted(ids_before - ids_after):
            if qdone > pqdone:
                events.append({"type": "QuestCompleted", "quest_id": qid})
            # иначе — ресинк/переполнение лога, событие НЕ эмитим

        # --- прогресс целей: монотонный рост + стабильность 2 кадра ---
        prog_now = _q_progress(info)
        for qid, val in prog_now.items():
            base = self._base_progress.get(qid)
            if base is None:
                self._base_progress[qid] = val
                continue
            if val < base:
                # Просадка = ресинк сервера. НЕ опускаем базу: иначе возврат
                # счётчика к прежнему значению выглядел бы как «рост» и рождал
                # ложный ObjectiveProgress (поймано тестом
                # test_resync_dip_does_not_emit_progress). Базу держим на
                # максимуме виденного, промежуточный кадр игнорируем.
                self._pending_progress.pop(qid, None)
                continue
            if val == base:
                self._pending_progress.pop(qid, None)
                continue
            cand, frames = self._pending_progress.get(qid, (val, 0))
            if cand != val:
                self._pending_progress[qid] = (val, 1)
                continue
            frames += 1
            if frames >= STABILITY_FRAMES:
                events.append({"type": "ObjectiveProgress", "quest_id": qid,
                               "old": base, "new": val})
                self._base_progress[qid] = val
                self._pending_progress.pop(qid, None)
            else:
                self._pending_progress[qid] = (val, frames)

        # --- лут: новый itemId в сумках ---
        before_items, after_items = _inv_ids(prev), _inv_ids(info)
        for item in after_items:
            if item not in before_items:
                events.append({"type": "ItemLooted", "item_id": item})

        # --- застревание: история кадров без движения ---
        moved = math.hypot(pos[0] - ppos[0], pos[1] - ppos[1])
        if moved < STUCK_EPS:
            self._still_frames += 1
            if self._still_frames >= STUCK_FRAMES and not self._stuck_emitted:
                events.append({"type": "NavigationStuck",
                               "frames": self._still_frames, "pos": list(pos)})
                self._stuck_emitted = True
        else:
            self._still_frames = 0
            self._stuck_emitted = False

        self.prev = info
        return events
