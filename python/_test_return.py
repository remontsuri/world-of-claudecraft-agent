"""Red test for return_to_giver: must find a quest WITH turnInNpc, not just the
first active quest (which may lack turnInNpc and cause FAILURE).

Reproduces the live bug: quests.active[0] is a quest without turnInNpc, but a
LATER active/ready quest HAS turnInNpc. return_to_giver must still navigate.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", os.path.dirname(os.path.abspath(__file__)))

from browser_env import BrowserEnv
from quest_skill import return_to_giver
from quest_capability import QuestCapability
from world_state import build_world_state

# Synthetic info: first active quest has NO turnInNpc; a later one HAS it.
INFO = {
    "player": {"hp": 93, "maxHp": 93, "level": 4, "dead": False, "facing": 0,
               "pos": {"x": 0, "z": 0}},
    "player_pos": [0, 0],
    "nearby": [],
    "quests": {
        "active": [
            {"id": "q_wolves", "state": "active", "objectives": [{"current": 0, "required": 5}],
             "turnInNpc": None},
            {"id": "q_prof_attune_smith", "state": "active", "objectives": [],
             "turnInNpc": {"id": 12, "x": 1.76, "z": 16.12}},
        ],
        "ready": [],
        "done": [],
    },
    "inventory": [],
}


def main():
    env = BrowserEnv.__new__(BrowserEnv)  # bypass __init__ (no bridge needed)
    env._last_info = INFO
    cap = QuestCapability(env)
    q = cap.find_active_quest()
    print("find_active_quest ->", q.get("id"), "| turnInNpc =", (q.get("turnInNpc") or {}).get("x"))
    # The bug: q is q_wolves (no turnInNpc) -> return_to_giver would FAIL.
    assert q.get("turnInNpc") is not None, (
        f"find_active_quest returned {q.get('id')} with NO turnInNpc "
        f"-> return_to_giver would FAIL (real bug)")
    # If we got here, the bug is fixed (find_active_quest skips turnInNpc-less quests)
    print("PASS test_return_to_giver_finds_turnin_quest")


def test_decide_return_picks_turnin_quest():
    """decide() for return_to_giver must put a quest WITH turnInNpc in ctx, not
    the first active quest (which may lack turnInNpc -> return_to_giver FAILURE)."""
    import policy
    from memory import ExperienceStore
    npc = {"kind": "npc", "id": 12, "name": "Darva", "questIds": ["q_prof_attune_smith"]}
    info = {
        "player": {"hp": 93, "maxHp": 93, "level": 4, "dead": False, "facing": 0, "pos": {"x": 0, "z": 0}},
        "player_pos": [0, 0],
        "nearby": [npc],
        "quests": {
            "active": [
                {"id": "q_wolves", "state": "active", "objectives": [{"current": 0, "required": 5}],
                 "turnInNpc": None},
                {"id": "q_prof_attune_smith", "state": "active", "objectives": [],
                 "turnInNpc": {"id": 12, "x": 1.76, "z": 16.12}},
            ],
            "ready": [], "done": [],
        },
        "inventory": [],
    }
    ws = build_world_state(info)
    EXP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experience_autonomous.json")
    gm = policy.GoalManager(ExperienceStore(path=EXP), seed=1)
    sampled = None
    for s in range(300):
        g = policy.GoalManager(ExperienceStore(path=EXP), seed=s)
        action, ctx = g.decide(info, ws=ws, exploration_weight=1.0)
        if action == "return_to_giver":
            sampled = (action, ctx)
            break
    assert sampled is not None, "decide never selected return_to_giver in 300 seeds"
    _, ctx = sampled
    assert "quest" in ctx, "return_to_giver ctx missing quest"
    q = ctx["quest"]
    assert (q.get("turnInNpc") or {}).get("x") is not None, (
        f"return_to_giver ctx.quest={q.get('id')} has NO turnInNpc -> would FAIL")
    print("PASS test_decide_return_picks_turnin_quest")


if __name__ == "__main__":
    tests = [main, test_decide_return_picks_turnin_quest]
    fails = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"\nTEST FAIL (reproduces bug): {e}")
            fails += 1
        except Exception as e:
            print(f"\nTEST ERROR: {e}")
            fails += 1
    print("\nTEST PASS" if fails == 0 else f"\n{fails} TEST(S) FAILED")
    sys.exit(1 if fails else 0)
