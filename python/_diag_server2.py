"""READ-ONLY: are two concurrent envs INDEPENDENT (distinct player state)?

_diag_server showed identical post-step positions, but that could just be
identical spawn + identical 10-forward sequence. Here A takes 5 steps, B takes
25 steps (different sequences); if they are independent sims, positions differ.
If a single shared server with one player, B's position would be driven only by
B's own steps (still could differ) — so we also check that A's position is NOT
affected by B running concurrently (sample A before/after B starts).
"""

import threading
import time

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD
from quest_capability import QuestCapability


def accept(env, seed):
    cap = QuestCapability(env)
    if cap.find_active_quest() is not None:
        return
    for _ in range(24):
        env.base.step(ACT_FORWARD)
        env.base.step(3)  # ACT_TURN_LEFT
        near = env._last_info.get("nearby") or []
        g = [e for e in near
             if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
        if g:
            qid = (g[0].get("questIds") or [None])[0]
            env._navigate_to_coord(g[0]["x"], g[0]["z"], max_steps=80)
            env._last_info = env.base.accept_quest(str(qid))
            break


def run(tag, seed, nsteps, out):
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=seed)
    env.reset(seed=seed)
    accept(env, seed)
    for _ in range(nsteps):
        env.base.step(ACT_FORWARD)
    out[tag] = env._last_info.get("player_pos")
    env.close()


res = {}
# A: 5 steps. B: 25 steps. Different sequences.
tA = threading.Thread(target=run, args=("A", 4242, 5, res))
tB = threading.Thread(target=run, args=("B", 909, 25, res))
tA.start()
time.sleep(0.3)
tB.start()
tA.join(60); tB.join(60)
print(f"A (5 fwd):  {res.get('A')}")
print(f"B (25 fwd): {res.get('B')}")
if res.get("A") and res.get("B"):
    dx = abs(res["A"][0] - res["B"][0]) + abs(res["A"][1] - res["B"][1])
    print(f"distance between positions = {dx:.2f}")
    print("INDEPENDENT (different positions)" if dx > 1.0 else "SUSPICIOUS (shared state)")
