"""smoke_autonomy.py — живой прогон автономного контура через настоящий мост.

НЕ обучение: проверка что петля замкнута на реальной игре.
Мост: browser_bridge.cjs (WOC_TAB_MATCH=localhost:5173 для офлайна).

Запуск: cd python && python smoke_autonomy.py [steps]
"""
import json
import sys
import time
import urllib.request

from world_state import build_world_state
from observation import encode_observation
from action_mask import index_of, endpoint_of
from autonomy import AutonomyLoop

BRIDGE = "http://127.0.0.1:8791"


def call(payload, timeout=60):
    req = urllib.request.Request(
        BRIDGE, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    d = json.loads(raw)
    info = d.get("info") or {}
    if isinstance(info, dict) and "info" in info:
        info = info["info"]
    return d, info


def main(steps=20):
    _, info = call({"action": "snapshot"})
    loop = AutonomyLoop(min_dwell=10)

    try:
        from memory import ExperienceStore
        from policy import GoalManager
        policy = GoalManager(ExperienceStore())
    except Exception as e:
        policy = None
        print("  (policy unavailable: %s)" % str(e)[:70])

    ALL = ["farm", "loot", "gather", "buy", "sell_junk", "accept_quest",
           "turn_in_quest", "heal", "equip", "craft", "respawn", "explore"]

    print("=== live autonomy smoke: %d steps ===" % steps)
    print("class=%s copper=%s kills=%s" % (
        info.get("player_class"), info.get("copper"), info.get("kills")))

    for i in range(steps):
        ws = build_world_state(info)
        try:
            cands = policy._candidates(info, ws, goal=None) if policy else list(ALL)
        except Exception:
            cands = list(ALL)
        if not cands:
            cands = list(ALL)

        pre = loop.before_action(info, ws, cands)
        sub = pre["subgoal"] or {}
        navcmd = pre.get("nav_command")

        try:
            if navcmd:
                # навигация: координаты цели ИЗ ИГРЫ, шаги режем чтобы
                # один вызов не висел дольше таймаута (25 * 220ms ~ 5.5s)
                skill = "explore"
                cmd = dict(navcmd)
                cmd["max_steps"] = 25
                _, after = call(cmd, timeout=180)
            else:
                skill = pre["forced_skill"] or (pre["candidates"][0]
                                               if pre["candidates"] else "explore")
                ep = endpoint_of(skill)
                if ep == "respawn":
                    # respawn — свой endpoint моста (двухэтапная цепочка)
                    _, after = call({"action": "respawn"}, timeout=180)
                else:
                    idx = index_of(skill)
                    _, after = call({"action": "step",
                                     "idx": idx if idx >= 0 else 0, "cmd": {}},
                                    timeout=120)
        except Exception as e:
            print("  %2d %-13s -> BRIDGE_ERR %s" % (i + 1, skill, str(e)[:50]))
            try:
                _, after = call({"action": "snapshot"}, timeout=60)
            except Exception:
                print("  bridge unreachable, stopping")
                break

        ws_after = build_world_state(after)
        rec = loop.after_action(skill, after, ws_after)

        oa = encode_observation(ws_after, after)
        print(" %2d %-13s -> %-8s sub=%-12s nav=%-8s mob=%-7s kills=%s" % (
            i + 1, skill, rec["skill_result"],
            (sub.get("subgoal") or "-"),
            (pre.get("nav_status") or "-"),
            (oa.get("target") or {}).get("distance"),
            (oa.get("world") or {}).get("kills")))
        info = after
        time.sleep(0.05)

    s = loop.summary()
    print("\n=== summary ===")
    print("steps=%d success=%d no_op=%d failure=%d" % (
        s["steps"], s.get("success", 0), s.get("no_op", 0), s.get("failure", 0)))
    print("success_rate=%.2f no_op_rate=%.2f" % (s["success_rate"], s["no_op_rate"]))
    print("masked_out=%d loops_tripped=%d recoveries=%d" % (
        s["masked_out"], s["loops_tripped"], s["recoveries"]))
    print("nav: commands=%d arrived=%d stuck=%d" % (
        s.get("nav_commands", 0), s.get("nav_arrived", 0), s.get("nav_stuck", 0)))
    print("subgoals:", s["subgoals"])
    return 0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    sys.exit(main(n))
