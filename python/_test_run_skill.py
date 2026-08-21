"""Red test: Agent._run_skill must report return_to_giver's real outcome.

Bug: agent._run_skill (agent.py:76-81) maps EVERY non-SUCCESS return value from
quest_skill.return_to_giver to verdict="INCONCLUSIVE". So a genuine FAILURE
(no known giver position -> can never navigate) is reported as INCONCLUSIVE,
exactly like PARTIAL (leg ran, not reached yet). The verifier/reward path then
cannot distinguish "agent is stuck because it has no target" from "agent made
measurable progress". A return_to_giver that will NEVER succeed must surface as
FAILURE so the policy learns not to pick it in that state.

Reproduce: build a real Agent over a BrowserEnv whose _last_info has a quest
WITH turnInNpc but player far away AND no world_mem entry -> return_to_giver
returns FAILURE (giver_pos None because ctx quest has no turnInNpc here).
We force ctx to a quest without turnInNpc to make return_to_giver return FAILURE,
then assert _run_skill does NOT hide it as INCONCLUSIVE.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import Agent
from browser_env import BrowserEnv
from memory import ExperienceStore, WorldMemory

EXP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experience_autonomous.json")


def _make_agent():
    env = BrowserEnv.__new__(BrowserEnv)  # no bridge
    mem = ExperienceStore(path=EXP)
    # NOTE: play_autonomous.py creates Agent WITHOUT world_mem (local world_mem is
    # never passed). Reproduce that exact contract so the test reflects prod.
    return Agent(env, mem, seed=1, world_mem=WorldMemory())


def test_return_to_giver_failure_surfaces():
    """A return_to_giver that genuinely cannot navigate must report FAILURE."""
    agent = _make_agent()
    # quest with NO turnInNpc -> giver_pos None -> return_to_giver returns FAILURE
    info = {
        "player": {"hp": 93, "maxHp": 93, "dead": False, "pos": {"x": 0, "z": 0}},
        "player_pos": [0, 0],
        "nearby": [],
        "quests": {
            "active": [{"id": "q_wolves", "state": "active",
                        "objectives": [{"current": 0, "required": 5}],
                        "turnInNpc": None}],
            "ready": [], "done": [],
        },
        "inventory": [],
    }
    agent.env._last_info = info
    ctx = {"quest": info["quests"]["active"][0]}
    after, verdict, kind = agent._run_skill("return_to_giver", ctx, info)
    assert kind == "OK", f"unexpected outcome_kind {kind}"
    assert verdict == "FAILURE", (
        f"return_to_giver FAILURE was masked as {verdict!r} "
        f"(agent.py maps all non-SUCCESS to INCONCLUSIVE)")
    print("PASS test_return_to_giver_failure_surfaces")


def test_return_to_giver_partial_stays_inconclusive():
    """A leg that ran but did not arrive (PARTIAL) must stay INCONCLUSIVE."""
    agent = _make_agent()
    info = {
        "player": {"hp": 93, "maxHp": 93, "dead": False, "pos": {"x": 0, "z": 0}},
        "player_pos": [0, 0],
        "nearby": [],
        "quests": {
            "active": [{"id": "q_prof", "state": "active", "objectives": [],
                        "turnInNpc": {"id": 12, "x": 1.76, "z": 16.12}}],
            "ready": [], "done": [],
        },
        "inventory": [],
    }
    agent.env._last_info = info
    # make navigate "run but not arrive" -> return_to_giver returns PARTIAL
    agent.env._navigate_to_coord = lambda *a, **k: False
    ctx = {"quest": info["quests"]["active"][0]}
    after, verdict, kind = agent._run_skill("return_to_giver", ctx, info)
    assert kind == "OK"
    assert verdict == "INCONCLUSIVE", f"PARTIAL should stay INCONCLUSIVE, got {verdict!r}"
    print("PASS test_return_to_giver_partial_stays_inconclusive")


if __name__ == "__main__":
    fails = 0
    for t in [test_return_to_giver_failure_surfaces,
              test_return_to_giver_partial_stays_inconclusive]:
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
