"""Diagnose why return_to_giver returns FAILURE despite nav working.

Directly builds the Agent with the live bridge and forces return_to_giver,
printing the giver_pos resolution and the verdict. Phase-1 evidence.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", os.path.dirname(os.path.abspath(__file__)))

from browser_env import BrowserEnv
from agent import Agent
from memory import ExperienceStore, WorldMemory

EXP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experience_autonomous.json")
WM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_memory.json")


def main():
    env = BrowserEnv()
    mem = ExperienceStore(path=EXP)
    # mirror play_autonomous: Agent(env, mem, seed=...) -- NO world_mem passed
    agent = Agent(env, mem, seed=123)

    # force a return_to_giver and capture what happens
    rec = agent.step_forced("return_to_giver", learn=False)
    print("=== return_to_giver forced (Agent with BrowserEnv, no world_mem) ===")
    print("verdict:", rec.get("verdict"))
    print("outcome_kind:", rec.get("outcome_kind"))
    print("action:", rec.get("action"))

    # inspect giver_pos resolution manually (mirror quest_skill.return_to_giver)
    from quest_capability import QuestCapability
    cap = QuestCapability(env)
    q = cap.find_active_quest()
    print("find_active_quest ->", q.get("id") if q else None,
          "| turnInNpc.x =", (q.get("turnInNpc") or {}).get("x") if q else None)
    if q:
        qid = q.get("id")
        gp = wm.giver_pos(qid) if wm else None
        print("world_mem.giver_pos =", gp)
        tn = q.get("turnInNpc") or {}
        print("fallback turnInNpc =", tn.get("x"), tn.get("z"))


if __name__ == "__main__":
    main()
