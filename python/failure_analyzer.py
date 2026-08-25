"""failure_analyzer.py — классификация каждой FAILURE в структурированное знание.

План 2026-08-24, пункт 4 (отдельным изменением). Контракт из плана:

    { "action": "turn_in", "failure": "QUEST_FAILURE",
      "context": {...}, "cause": "...", "fix": "...", "retry": bool }

Принцип: НЕ трогаем существующие слои (self_reflection, event_bus,
replay_buffer). Это самостоятельный анализатор: на вход — rec шага
(тот же dict, что идёт в refl.observe), на выходе — запись о причине
неудачи + накопленная статистика cause -> recommended_fix.

Категории (из плана): SURVIVAL/COMBAT/NAVIGATION/QUEST/INTERACTION/
BRIDGE/TIMEOUT/PLANNING/RESOURCE/UNKNOWN.
"""
import time
from collections import Counter


# Пороги (в ярдах / долях HP) — только наблюдаемые факты, не правила игры
TURNIN_RANGE = 7.0          # авторитетный INTERACT_RANGE+2 (quest_truth)
LOW_HP = 0.30               # danger-порог world_state
NAV_STUCK_MIN_STEPS = 8     # подряд одинаковые nav-действия без прогресса


def classify(rec):
    """Один шаг -> запись анализа или None (если шаг не провал).

    Возвращает dict:
      action, failure (категория), cause, fix, retry, context{...}, t
    """
    if not isinstance(rec, dict):
        return None
    verdict = (rec.get("verdict") or "").upper()
    kind = (rec.get("kind") or "").upper()
    action = rec.get("action") or "?"
    is_failure = verdict in ("FAILURE", "ENV_ERROR") or kind == "ENV_ERROR"
    if not is_failure:
        return None

    hp = rec.get("hp")
    dist = rec.get("dist")
    goal = rec.get("goal") or ""
    quest_status = rec.get("quest_status") or ""

    # --- BRIDGE / INFRA ---
    if verdict == "ENV_ERROR" or kind == "ENV_ERROR":
        return _rec(action, "BRIDGE_FAILURE", "bridge_unreachable",
                    "wait_retry", retry=True,
                    context={"goal": goal, "step": rec.get("step")})
    # --- TIMEOUT: действие зависло (маркер от cmd_queue прокидывается сюда) ---
    err = str((rec.get("error") or "")).lower()
    if "timeout" in err:
        return _rec(action, "TIMEOUT_FAILURE", "command_hung",
                    "skip_and_continue", retry=True,
                    context={"goal": goal})

    # --- SURVIVAL: умер при выполнении ---
    deaths = rec.get("deaths")
    if deaths is not None and isinstance(deaths, (int, float)) and action != "respawn":
        # рост смертей фиксируется отдельно в play_autonomous; здесь ловим
        # провалы действий при критическом HP
        pass
    if hp is not None and hp < LOW_HP:
        return _rec(action, "SURVIVAL_FAILURE", f"low_hp_{round(hp,2)}",
                    "heal_or_retreat_first", retry=False,
                    context={"hp": hp, "action": action, "cell": rec.get("cell")})

    # --- QUEST / INTERACTION: turn_in ---
    if action == "turn_in_quest":
        if dist is not None and dist > TURNIN_RANGE:
            return _rec(action, "INTERACTION_FAILURE",
                        f"too_far_{round(dist,1)}yd",
                        "move_closer_then_turn_in", retry=True,
                        context={"dist": dist, "quest_status": quest_status,
                                 "goal": goal})
        # рядом, но всё равно провал: фантомный ready / cadence / bags
        return _rec(action, "QUEST_FAILURE", "turn_in_rejected_close_range",
                    "verify_quest_state_not_phantom", retry=False,
                    context={"dist": dist, "quest_status": quest_status,
                             "goal": goal})

    # --- NAVIGATION: return_to_giver не сократил дистанцию ---
    if action == "return_to_giver":
        return _rec(action, "NAVIGATION_FAILURE", "no_distance_progress",
                    "try_explore_reposition", retry=True,
                    context={"dist": dist, "goal": goal})

    # --- COMBAT: farm/spell провалились ---
    if action in ("farm", "cast_fireball", "cast_frostbolt"):
        return _rec(action, "COMBAT_FAILURE", "attack_no_effect",
                    "retarget_nearest_weak_mob", retry=True,
                    context={"hp": hp, "cell": rec.get("cell"),
                             "qprog": rec.get("qprog")})

    # --- RESOURCE: продать не удалось ---
    if action == "sell_junk":
        return _rec(action, "RESOURCE_FAILURE", "nothing_sold_no_vendor_gain",
                    "check_vendor_proximity", retry=True,
                    context={"hp": hp, "cell": rec.get("cell")})

    # --- PLANNING: accept и прочие квестовые действия ---
    if action in ("accept_quest", "gather", "loot", "heal"):
        cat = "PLANNING_FAILURE" if action == "accept_quest" else "QUEST_FAILURE"
        return _rec(action, cat, f"{action}_rejected",
                    "verify_preconditions", retry=True,
                    context={"goal": goal, "quest_status": quest_status})

    return _rec(action, "UNKNOWN_FAILURE", "unclassified",
                "log_for_review", retry=False,
                context={"verdict": verdict, "kind": kind})


def _rec(action, failure, cause, fix, retry, context):
    return {
        "t": time.time(),
        "action": action,
        "failure": failure,
        "cause": cause,
        "fix": fix,
        "retry": bool(retry),
        "context": context,
    }


class FailureAnalyzer:
    """Накапливает причины неудач и выдаёт агрегированные рекомендации.

    Это данные для обучения (план, раздел 11): после N шагов агент видит
    'turn_in failure 93%, most common condition: distance 3-5' — гипотезы
    для экспериментов, а не догадки.
    """

    def __init__(self, path=None, max_records=500):
        import json, os
        self.path = path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "failure_analysis.json")
        self.max_records = max_records
        self.records = []      # последние max_records записей classify()
        self.causes = Counter()          # (action, cause) -> count
        self.fixes = Counter()           # fix -> count
        self._load()

    def _load(self):
        import json
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.records = d.get("records", [])[-self.max_records:]
            self.causes = Counter({tuple(k.split("|", 1)): v
                                   for k, v in d.get("causes", {}).items()})
            self.fixes = Counter(d.get("fixes", {}))
        except Exception:
            pass

    def save(self):
        import json
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({
                    "records": self.records[-self.max_records:],
                    "causes": {"|".join(k): v for k, v in self.causes.items()},
                    "fixes": dict(self.fixes),
                }, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def observe_step(self, rec):
        """Прокормить один шаг; вернуть запись анализа либо None."""
        a = classify(rec)
        if a is None:
            return None
        self.records.append(a)
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]
        self.causes[(a["action"], a["cause"])] += 1
        self.fixes[a["fix"]] += 1
        return a

    def top_failures(self, n=5):
        """Топ причин: [(action, cause, count), ...]."""
        return [(a, c, k) for (a, c), k in self.causes.most_common(n)]

    def recommendations(self, min_count=3):
        """Действенные выводы: причины, повторившиеся min_count раз.

        Возвращает [{action, cause, count, fix}] — вход для гипотез
        woc-self-improvement (план, раздел 9).
        """
        out = []
        for (action, cause), count in self.causes.most_common():
            if count < min_count:
                break
            fix = next((r["fix"] for r in reversed(self.records)
                        if r["action"] == action and r["cause"] == cause),
                       "verify_preconditions")
            out.append({"action": action, "cause": cause,
                        "count": count, "fix": fix})
        return out

    def summary_line(self):
        """Одна строка для финального summary прогона."""
        total = sum(self.causes.values())
        if total == 0:
            return "failures=0"
        tops = "; ".join(f"{a}:{c}x{cnt}" for (a, c), cnt in self.causes.most_common(3))
        return f"failures={total} ({tops})"
