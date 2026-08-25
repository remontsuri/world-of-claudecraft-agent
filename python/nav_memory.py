"""nav_memory.py — Navigation Memory (план 2026-08-24, п.5, отдельным изменением).

Учится на маршрутах: позиция A -> позиция B, сколько раз прошло успешно,
сколько застреваний, средняя дистанция. Позволяет отличать «я ещё иду»
от «я 40 секунд хожу по кругу» и подсказывать альтернативный маршрут.

Хранит записи вида:
    key = "x1,z1->x2,z2"  (ячейки ~2 yd, округление)
    { attempts, successes, stuck, avg_dist, last_used }

API:
    record_attempt(from_pos, to_pos) -> route_key
    record_result(route_key, success, dist_progress)
    is_stuck(from_pos, to_pos) -> bool   # >=3 застреваний из последних 5 попыток
    best_known(from_pos) -> список целей, куда ходили (для подсказок политики)

Никаких правил игры — только наблюдаемая статистика.
"""
import os
import time
from collections import deque

CELL = 2.0          # размер ячейки округления (ярды)
STUCK_WINDOW = 5    # последние N попыток для решения о застревании
STUCK_THRESHOLD = 3 # >=3 неудач в окне -> маршрут считается проблемным


def _cell(v):
    return round(float(v) / CELL)


def route_key(from_pos, to_pos):
    """Стабильный ключ маршрута по ячейкам."""
    try:
        a = f"{_cell(from_pos[0])},{_cell(from_pos[1])}"
        b = f"{_cell(to_pos[0])},{_cell(to_pos[1])}"
        return f"{a}->{b}"
    except Exception:
        return None


class NavMemory:
    def __init__(self, path=None, max_routes=2000):
        import json
        self.path = path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "nav_memory.json")
        self.max_routes = max_routes
        self.routes = {}  # key -> {attempts, successes, stuck, avg_dist, last_used,
                          #           recent: deque[bool]}
        self._load()

    def _load(self):
        import json
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in (data.get("routes") or {}).items():
                v["recent"] = deque(v.get("recent", []), maxlen=STUCK_WINDOW)
                self.routes[k] = v
        except Exception:
            pass

    def save(self):
        import json
        try:
            out = {}
            for k, v in self.routes.items():
                vv = dict(v)
                vv["recent"] = list(v["recent"])
                out[k] = vv
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"routes": out}, f, ensure_ascii=False)
        except Exception:
            pass

    # ---- API ----

    def record_attempt(self, from_pos, to_pos):
        """Начало движения. Возвращает ключ маршрута (или None)."""
        k = route_key(from_pos, to_pos)
        if not k:
            return None
        r = self.routes.setdefault(k, {
            "attempts": 0, "successes": 0, "stuck": 0,
            "avg_dist": 0.0, "last_used": 0, "recent": deque(maxlen=STUCK_WINDOW),
        })
        r["attempts"] += 1
        r["last_used"] = time.time()
        if len(self.routes) > self.max_routes:
            # вытесняем самые старые
            oldest = sorted(self.routes.items(), key=lambda kv: kv[1]["last_used"])
            for ok_, _ in oldest[: len(oldest) - self.max_routes]:
                del self.routes[ok_]
        return k

    def record_result(self, route_key_, success, dist_progress=0.0):
        """Итог попытки: дошли ли + насколько сократилась дистанция."""
        if not route_key_ or route_key_ not in self.routes:
            return
        r = self.routes[route_key_]
        stuck = (not success) and (dist_progress <= 0.5)
        if success:
            r["successes"] += 1
        elif stuck:
            r["stuck"] += 1
        else:
            r["stuck"] += 1 if dist_progress < 2.0 else 0
        r["recent"] = r.get("recent") or deque(maxlen=STUCK_WINDOW)
        r["recent"].append(bool(success))
        # экспоненциальное среднее дистанции прогресса
        dp = max(0.0, float(dist_progress or 0))
        r["avg_dist"] = round(r["avg_dist"] * 0.7 + dp * 0.3, 2) \
            if r["avg_dist"] else round(dp, 2)

    def is_stuck_route(self, from_pos, to_pos):
        """Маршрут проблемный? >=STUCK_THRESHOLD неудач ПОДРЯД в конце окна.

        «Хожу по кругу» = последние попытки одна за другой без успеха.
        Чередование fail/success — не застревание (маршрут работает, но
        с ошибками).
        """
        k = route_key(from_pos, to_pos)
        r = self.routes.get(k or "")
        if not r:
            return False
        recent = list(r.get("recent") or [])
        if len(recent) < STUCK_WINDOW:
            return False
        tail_failures = 0
        for ok_ in reversed(recent):
            if ok_:
                break
            tail_failures += 1
        return tail_failures >= STUCK_THRESHOLD

    def route_stats(self, from_pos, to_pos):
        k = route_key(from_pos, to_pos)
        r = self.routes.get(k or "")
        if not r:
            return None
        return {
            "attempts": r["attempts"],
            "success_rate": round(r["successes"] / max(r["attempts"], 1), 2),
            "stuck": r["stuck"],
            "avg_dist": r["avg_dist"],
        }
