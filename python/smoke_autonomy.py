"""smoke_autonomy.py — живой прогон автономного контура через мост.

НЕ обучение: только проверка что петля замкнута на реальной игре.
Запуск: cd python && python smoke_autonomy.py [steps]
"""
import json
import sys
import time
import urllib.request

from world_state import build_world_state
from observation import encode_observation
from action_mask import index_of
from autonomy import AutonomyLoop
from policy import GoalManager

BRIDGE = "http://127.0.0.1:8791"


def call(payload, timeout=30):
    req = urllib.request.Request(
        BRIDGE, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    d = json.loads(raw)
    info = d.get("info") or {}
    if isinstance(info, dict) and "info" in info:
        info = info["info"]
    return d, info


def _target_pos(obs, kind):
    """Координаты цели навигации из observation.

    kind: 'quest_giver' | 'vendor' | 'node' | 'mob'
    Возвращает (x, z) или None. Координаты берутся ИЗ ИГРЫ (obs.raw_entities),
    никаких статических таблиц.
    """
    ents = (obs.get("_entities") or [])
    if not ents:
        return None
    def pick(pred):
        best, bd = None, 1e9
        for e in ents:
            if not pred(e):
                continue
            d = e.get("_dist", 1e9)
            if d < bd:
                bd, best = d, e
        return best
    if kind == "quest_giver":
        e = pick(lambda e: e.get("questIds") or e.get("questId"))
    elif kind == "vendor":
        e = pick(lambda e: e.get("vendorItems") or e.get("isVendor"))
    elif kind == "node":
        e = pick(lambda e: (e.get("kind") == "node") or e.get("nodeType"))
    else:
        e = pick(lambda e: e.get("kind") == "mob" and not e.get("dead"))
    if not e:
        return None
    x, z = e.get("x"), e.get("z")
    if x is None or z is None:
        pos = e.get("pos") or {}
        x, z = pos.get("x"), pos.get("z")
    if x is None or z is None:
        return None
    return float(x), float(z)


def main(steps=30):
    _, info = call({"action": "snapshot"})
    loop = AutonomyLoop(min_dwell=10)
    try:
        from memory import ExperienceStore
        policy = GoalManager(ExperienceStore())
    except Exception as e:
        policy = None
        print("  (policy unavailable, using contract candidates: %s)" % str(e)[:70])

    print("=== live autonomy smoke: %d steps ===" % steps)
    print("class=%s copper=%s" % (info.get("player_class"), info.get("copper")))

    for i in range(steps):
        ws = build_world_state(info)
        obs = encode_observation(ws, info)

        try:
            cands = (policy._candidates(info, ws, goal=None) if policy
                     else ["farm", "loot", "gather", "buy", "sell_junk",
                           "accept_quest", "turn_in_quest", "heal", "explore"])
        except Exception as e:
            cands = ["farm", "loot", "explore"]
            if i == 0:
                print("  (policy._candidates unavailable: %s)" % str(e)[:60])

        pre = loop.before_action(info, ws, cands)
        skill = pre["forced_skill"] or (pre["candidates"][0] if pre["candidates"] else "explore")
        sub = pre["subgoal"] or {}
        idx = index_of(skill)

        if skill == "explore" or idx < 0:
            # explore = НАВИГАЦИЯ к цели subgoal-а, координаты из игры
            tgt = _target_pos(pre["obs"], sub.get("target") or "mob")
            if tgt:
                _, after = call({"action": "navigate",
                                 "x": tgt[0], "z": tgt[1], "max_steps": 40}, timeout=60)
            else:
                _, after = call({"action": "step", "idx": 0, "cmd": {}})
        else:
            _, after = call({"action": "step", "idx": idx, "cmd": {}})
        ws_after = build_world_state(after)
        rec = loop.after_action(skill, after, ws_after)

        if i < 12 or i % 5 == 0:
            gd = (encode_observation(ws_after, after).get("quest") or {}).get("giver_distance")
            print(" %2d %-14s -> %-8s sub=%-16s giver_dist=%s" % (
                i + 1, skill, rec["skill_result"],
                rec.get("subgoal") or "-", gd))
        info = after
        time.sleep(0.05)

    s = loop.summary()
    print("\n=== summary ===")
    print("steps=%d success=%d no_op=%d failure=%d" % (
        s["steps"], s.get("success", 0), s.get("no_op", 0), s.get("failure", 0)))
    print("success_rate=%.2f no_op_rate=%.2f" % (s["success_rate"], s["no_op_rate"]))
    print("masked_out=%d loops_tripped=%d recoveries=%d" % (
        s["masked_out"], s["loops_tripped"], s["recoveries"]))
    print("subgoals:", s["subgoals"])
    return 0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    sys.exit(main(n))
