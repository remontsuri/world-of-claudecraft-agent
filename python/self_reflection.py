"""Self-reflection loop (the missing 'делал выводы' step).

Every SAVE_EVERY steps the agent now runs a structured self-review over its own
recent history and writes CONCLUSIONS to a persistent journal. Conclusions are
not just logs: each carries a machine-actionable hint consumed by policy.py
through StrategyMemory preference keys, so tomorrow's decisions differ from
today's without human intervention.

Conclusions the loop can draw (each -> a strategy key):
  1. DEATH_CLUSTER   — N deaths in window at one cell/zone: "this place kills me"
                       -> key death:<cell> ; policy can avoid when hp low.
  2. ACTION_SATURATION — one action >60% of window with ~zero reward:
                       "I am spinning on X" -> key spin:<action>.
  3. QUEST_STALL     — quest objective count unchanged for K steps while farming:
                       "farming here doesn't advance q_X" -> key stall:<quest>.
  4. VENDOR_CYCLE    — sell_junk SUCCESS repeatedly with rising copper:
                       "vendor route works" -> positive reinforcement only.
"""
import json
import os
import time
from collections import Counter


# Окно событий Event Bus (шаг 3 спеки 2026-08-24). Reflexion держит буфер
# коротким (1-3 свежих вывода), иначе контекст растёт без пользы; события
# копим чуть шире, чтобы видеть кластеры (например 2 смерти подряд).
EVENT_WINDOW = 40


class SelfReflection:
    """Rolling self-review over the recent step records + persistent journal."""

    def __init__(self, path=None, dirpath=None):
        # dirpath: каталог для журнала (удобно в тестах); path имеет приоритет
        if path is None and dirpath is not None:
            import os as _os
            path = _os.path.join(dirpath, "self_reflection.json")
        # Событийная память (Event Bus -> рефлексия). До 2026-08-24 события
        # вообще не доходили до обучения: модуль event_bus.py был мёртв,
        # 9 типов событий не читал никто, кроме unit-теста.
        self.recent_events = []
        self.path = path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "self_reflection.json")
        self.journal = []          # [{t, kind, detail}]
        self.window = []           # recent step dicts (bounded)
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.journal = data.get("journal", [])[-200:]
        except Exception:
            pass

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"journal": self.journal[-200:]}, f,
                          ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def observe_events(self, events):
        """Принять события Event Bus за шаг (QuestCompleted, PlayerDied,
        NavigationStuck, InventoryFull, ObjectiveProgress и т.д.).

        Хранится скользящее окно EVENT_WINDOW: выводы делаются по кластерам
        (2 смерти подряд, застревание, полные сумки), а не по одному кадру.
        """
        if not events:
            return
        for e in events:
            if isinstance(e, dict) and e.get("type"):
                self.recent_events.append(e)
        if len(self.recent_events) > EVENT_WINDOW:
            self.recent_events = self.recent_events[-EVENT_WINDOW:]

    def event_conclusions(self) -> list:
        """Вербальные уроки из событий (Reflexion: событие -> урок -> правило).

        Каждый вывод — dict {kind, key, detail, hint}. Ключ понимается
        политикой: stuck:<action> и spin:<action> подавляют вес,
        bags:full предпочитает продажу, quest:completed поощряет взять новый.
        """
        if not self.recent_events:
            return []
        out = []
        types = [e.get("type") for e in self.recent_events]

        # NAVIGATION_STUCK: путь не работает -> подавить текущую навигацию
        if "NavigationStuck" in types:
            out.append({
                "kind": "NAVIGATION_STUCK",
                "key": "stuck:return_to_giver",
                "detail": "навигация стоит на месте — цель недостижима этим путём",
                "hint": "reduce_weight",
            })

        # INVENTORY_FULL: полные сумки блокируют сдачу квеста (bagsFullError)
        if "InventoryFull" in types:
            out.append({
                "kind": "INVENTORY_FULL",
                "key": "bags:full",
                "detail": "сумки полны — сдача квеста будет отклонена, надо продать",
                "hint": "prefer_sell",
            })

        # DEATH_CLUSTER: две смерти в окне -> здесь опасно
        if types.count("PlayerDied") >= 2:
            out.append({
                "kind": "DEATH_CLUSTER",
                "key": "danger:zone",
                "detail": "две смерти за короткое окно — зона не по силам",
                "hint": "reduce_weight",
            })

        # QUEST_COMPLETED: закончил — бери следующий
        if "QuestCompleted" in types:
            out.append({
                "kind": "QUEST_COMPLETED",
                "key": "quest:completed",
                "detail": "квест сдан — стоит взять следующий у ближайшего NPC",
                "hint": "prefer_accept",
            })

        return out

    def observe(self, rec):
        """Feed one step record (autonomous_log-style dict)."""
        self.window.append({
            "step": rec.get("step"),
            "action": rec.get("action"),
            "verdict": rec.get("verdict"),
            "reward": rec.get("reward", 0.0),
            "hp": rec.get("hp"),
            "dist": rec.get("dist"),
            "cell": rec.get("cell"),
            "kills": rec.get("kills"),
            "qprog": rec.get("qprog"),
            "deaths": rec.get("deaths"),
            "quest_status": rec.get("quest_status"),
        })
        if len(self.window) > 150:
            self.window = self.window[-100:]

    def reflect(self) -> list:
        """Run the review; append conclusions to journal; return them."""
        conclusions = []
        w = self.window
        if len(w) < 30:
            return conclusions

        # 1. DEATH_CLUSTER: >=3 deaths in window, remember where
        deaths = [d for d in w if d.get("deaths") is not None]
        d_deaths = 0
        cells = Counter()
        prev = None
        for d in deaths:
            dv = d["deaths"]
            if prev is not None and dv > prev:
                d_deaths += 1
                cells[d.get("cell") or "?"] += 1
            prev = dv
        if d_deaths >= 2:
            worst = cells.most_common(1)
            if worst and worst[0][0] != "?":
                conclusions.append({
                    "kind": "DEATH_CLUSTER",
                    "detail": f"{d_deaths} deaths in last {len(w)} steps, "
                              f"worst cell {worst[0][0]} ({worst[0][1]}x)",
                    "key": f"death:{worst[0][0]}",
                    "hint": "avoid_when_low_hp",
                })

        # 2. ACTION_SATURATION: one action dominates the window while producing
        #    NO RESULT. Two shapes of "no result":
        #      a) near-zero avg reward (classic spinning), OR
        #      b) near-CONSTANT reward — a navigation treadmill: return_to_giver
        #         earns positive arrival reward every step, but kills/xp/qprog
        #         never move. R3 FIX (2026-08-23): shape (b) previously passed
        #         the |avg|<0.05 gate and the treadmill was invisible (measured
        #         run: 1860x return_to_giver with avg reward +0.31).
        acts = Counter(d.get("action") for d in w)
        if acts:
            top_a, top_n = acts.most_common(1)[0]
            if top_n / len(w) > 0.6 and top_n >= 25:
                rs = [d.get("reward", 0.0) for d in w if d.get("action") == top_a]
                avg_r = sum(rs) / max(len(rs), 1)
                var = sum((r - avg_r) ** 2 for r in rs) / max(len(rs), 1)
                flat_reward = abs(avg_r) < 0.05 or var < 1e-4
                if flat_reward:
                    conclusions.append({
                        "kind": "ACTION_SATURATION",
                        "detail": f"'{top_a}' took {top_n}/{len(w)} steps "
                                  f"with avg reward {avg_r:+.3f} - spinning",
                        "key": f"spin:{top_a}",
                        "hint": "reduce_weight",
                    })

        # 3. QUEST_STALL: objective counter frozen across the window while
        #    farming actions dominated
        qp_first = next((d.get("qprog") for d in w if d.get("qprog") is not None), None)
        qp_last = next((d.get("qprog") for d in reversed(w)
                        if d.get("qprog") is not None), None)
        farmish = sum(1 for d in w if d.get("action") in ("farm", "cast_fireball",
                                                          "cast_frostbolt"))
        if (qp_first is not None and qp_last is not None
                and qp_last == qp_first and farmish >= 15):
            conclusions.append({
                "kind": "QUEST_STALL",
                "detail": f"objective stuck at {qp_last} despite {farmish} "
                          f"combat steps - wrong mobs or wrong place",
                "key": "stall:objectives",
                "hint": "change_zone_or_target",
            })

        # 4. VENDOR_CYCLE: sells succeeding = good, keep it (positive note)
        sells_ok = sum(1 for d in w if d.get("action") == "sell_junk"
                       and d.get("verdict") == "SUCCESS")
        if sells_ok >= 5:
            conclusions.append({
                "kind": "VENDOR_CYCLE_OK",
                "detail": f"sell succeeded {sells_ok}x - bag pressure managed",
                "key": "cycle:sell",
                "hint": "keep_going",
            })

        t = time.time()
        for c in conclusions:
            c["t"] = t
        if conclusions:
            self.journal.extend(conclusions)
            self.journal = self.journal[-200:]
            self.save()
        return conclusions

    def hints(self) -> dict:
        """Machine-actionable hints aggregated from the journal tail.

        Returns {kind_prefix: detail} of the most recent conclusion per key.
        """
        out = {}
        for c in self.journal[-40:]:
            out[c["key"]] = {"kind": c["kind"], "detail": c["detail"],
                             "hint": c.get("hint")}
        return out
