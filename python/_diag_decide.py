"""Diagnose what policy.decide() produces for the live world state.

Reproduces the agent's decision path on a real snapshot WITHOUT running the
full loop, so we can see the (action, ctx) the agent would send to the bridge.
This is Phase-1 evidence gathering, not a fix.
"""
import os, sys, json, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", os.path.dirname(os.path.abspath(__file__)))

from world_state import build_world_state
from policy import GoalManager
from memory import ExperienceStore

EXP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experience_autonomous.json")


def snapshot():
    data = json.dumps({"action": "snapshot"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8791/", data=data,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=10))


def main():
    info = snapshot().get("info", {})
    ws = build_world_state(info)
    mem = ExperienceStore(path=EXP_PATH)
    gm = GoalManager(mem, seed=4242)

    # mimic what Agent._cycle does
    action, ctx = gm.decide(info, ws=ws, exploration_weight=1.0)
    print("=== DECIDE RESULT ===")
    print("action:", action)
    print("ctx keys:", list(ctx.keys()))
    if "quest" in ctx:
        print("  ctx.quest.id =", ctx["quest"].get("id"), "| state =", ctx["quest"].get("state"))
    if "npc" in ctx:
        print("  ctx.npc.id =", ctx["npc"].get("id"), "| name =", ctx["npc"].get("name"))
        print("  ctx.npc.questIds =", ctx["npc"].get("questIds"))
    if "questId" in ctx:
        print("  ctx.questId =", ctx["questId"])
    else:
        print("  ctx.questId = MISSING  <-- this is the bug if accept_quest chosen")

    # Show what _candidates would build for this state
    cands = gm._candidates(info, ws)
    print("=== CANDIDATES ===")
    print(cands)

    # Show nearby NPCs with questIds for comparison
    near = info.get("nearby") or []
    npcs = [e for e in near if (e.get("kind") == "npc" or e.get("type") == "npc") and (e.get("questIds") or e.get("questId"))]
    print("=== NEARBY QUEST NPCS ===")
    for n in npcs[:6]:
        print(f"  npcId={n.get('id')} name={n.get('name')} questIds={n.get('questIds')}")


if __name__ == "__main__":
    main()
