"""READ-ONLY probe: is there ONE shared headless sim server per machine?

If two HierarchicalWoWEnv instances run concurrently and one of them errors out
or both share state, we cannot parallelize B3 measurement across seeds. We test
by launching two envs at once and confirming both reset + step without crashing
or cross-talking (distinct player positions / independent quests).
"""

import threading
import time

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from quest_capability import QuestCapability


def run(tag, seed, out):
    try:
        env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=seed)
        env.reset(seed=seed)
        # accept welcome on both
        cap = QuestCapability(env)
        if cap.find_active_quest() is None:
            for _ in range(24):
                env.base.step(ACT_FORWARD)
                env.base.step(ACT_TURN_LEFT)
                near = env._last_info.get("nearby") or []
                g = [e for e in near
                     if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
                if g:
                    qid = (g[0].get("questIds") or [None])[0]
                    env._navigate_to_coord(g[0]["x"], g[0]["z"], max_steps=80)
                    env._last_info = env.base.accept_quest(str(qid))
                    break
        for _ in range(10):
            env.base.step(ACT_FORWARD)
        pos = env._last_info.get("player_pos")
        q = QuestCapability(env).find_active_quest()
        out[tag] = {"ok": True, "pos": pos, "quest": (q.get("id") if q else None),
                    "pid": id(env)}
        env.close()
    except Exception as ex:
        out[tag] = {"ok": False, "error": repr(ex)[:120]}


res = {}
t1 = threading.Thread(target=run, args=("A", 4242, res))
t2 = threading.Thread(target=run, args=("B", 909, res))
t1.start(); t2.start()
t1.join(60); t2.join(60)
print("A:", res.get("A"))
print("B:", res.get("B"))
if res.get("A", {}).get("ok") and res.get("B", {}).get("ok"):
    same = (res["A"].get("pos") == res["B"].get("pos"))
    print(f"CONCURRENT OK; positions equal (shared state?) = {same}")
else:
    print("CONCURRENT FAILED -> single shared server likely")
