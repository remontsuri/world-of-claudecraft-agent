"""Домашний якорь рабочей зоны (шаг #3 согласованного плана, Q6).

Проблема, которую решает (измерено 2026-08-24): агент ушёл на [-13, 275] —
позиция без мобов, трупов, узлов и гиверов. Там он физически не может ни
фармить, ни харвестить, ни сдавать квесты, но продолжает тратить шаги.
Ни Q-learning, ни LLM-мозг эту ситуацию не исправляют: у обоих нет понятия
«здесь нечего делать, надо вернуться».

Решение (консенсус с со-архитектором): запоминать ПОСЛЕДНЮЮ позицию, где
рядом были объекты действия, и возвращаться к ней, когда вокруг пусто.
Фолбэк — позиция гивера активного квеста (когерентно с логистикой).

Осознанное ограничение: якорь может указывать на зону, которая уже опустела
(мобы перебиты и не респавнились). Это приемлемо — возврат в бывшую рабочую
зону всё равно лучше стояния в пустоте, а следующий observe() перепишет
якорь, как только объекты найдутся.
"""
import json
import math
import os

# радиус, в котором объект считается «рядом» (yd)
OBJECT_RADIUS = 40.0
# дальше этого от якоря при пустом окружении — пора возвращаться
FAR_FROM_ANCHOR = 60.0


def _has_objects(info: dict) -> bool:
    """Есть ли рядом хоть один объект действия: живой моб, труп, узел, гивер."""
    for e in (info.get("nearby") or []):
        d = e.get("dist")
        if d is not None and d > OBJECT_RADIUS:
            continue
        kind = e.get("kind")
        if kind == "mob":
            return True                     # живой моб или труп — оба полезны
        if kind == "npc" and (e.get("questIds") or e.get("vendor")):
            return True
        if kind == "gather_node" or e.get("nodeType"):
            return True
    for n in ((info.get("gather") or {}).get("nearbyNodes") or []):
        if n.get("harvestable"):
            return True
    return False


class WorkAnchor:
    def __init__(self, path=None):
        self.path = path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "work_anchor.json")
        self.last_work_pos = None
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            pos = data.get("last_work_pos")
            if isinstance(pos, list) and len(pos) == 2:
                self.last_work_pos = [float(pos[0]), float(pos[1])]
        except Exception:
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"last_work_pos": self.last_work_pos}, f)
        except Exception:
            pass

    def observe(self, info: dict):
        """Запомнить позицию, если вокруг есть объекты действия."""
        pos = info.get("player_pos")
        if not (isinstance(pos, (list, tuple)) and len(pos) == 2):
            return
        if _has_objects(info):
            self.last_work_pos = [float(pos[0]), float(pos[1])]

    def needs_return(self, info: dict) -> bool:
        """Пусто вокруг И мы далеко от якоря -> надо возвращаться."""
        if _has_objects(info):
            return False
        if self.last_work_pos is None:
            return False
        pos = info.get("player_pos")
        if not (isinstance(pos, (list, tuple)) and len(pos) == 2):
            return False
        d = math.hypot(self.last_work_pos[0] - pos[0],
                       self.last_work_pos[1] - pos[1])
        return d > FAR_FROM_ANCHOR

    def return_target(self, info: dict):
        """Куда возвращаться: якорь, иначе гивер активного квеста, иначе None."""
        if self.last_work_pos is not None:
            return list(self.last_work_pos)
        quests = info.get("quests") or {}
        for q in ((quests.get("active") or []) + (quests.get("ready") or [])):
            npc = q.get("turnInNpc") or {}
            if npc.get("x") is not None:
                return [float(npc["x"]), float(npc["z"])]
        return None
