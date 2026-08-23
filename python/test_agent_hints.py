"""R4: the live Agent must wire reflection hints into its GoalManager.

Yesterday's hint loop existed only in tests: agent.py built GoalManager()
with no reflection_hints and play_autonomous never refreshed them. These
tests pin the contract:
  - Agent accepts a hints dict and passes it to its policy
  - Agent.refresh_hints() reloads from self_reflection.json (journal path)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def _fake_env():
    # hierarchical_env SKILLS list is import-time constant; a bare object is
    # enough for construction (Agent.__init__ does not touch env).
    class _E:
        pass
    return _E()


def test_agent_takes_hints_into_policy():
    from agent import Agent
    from memory import ExperienceStore
    mem = ExperienceStore(path=":memory:")
    ag = Agent(_fake_env(), mem, seed=1,
               reflection_hints={"spin:return_to_giver": {
                   "kind": "ACTION_SATURATION", "hint": "reduce_weight"}})
    assert getattr(ag.policy, "hints", None), \
        "Agent did not forward reflection_hints to GoalManager"


def test_agent_refresh_hints_reads_journal(tmp_path=None):
    import json
    import tempfile
    td = tempfile.mkdtemp()
    jr = os.path.join(td, "self_reflection.json")
    with open(jr, "w", encoding="utf-8") as f:
        json.dump({"journal": [
            {"kind": "ACTION_SATURATION", "key": "spin:return_to_giver",
             "detail": "x", "hint": "reduce_weight",
             "t": __import__("time").time()}]}, f)
    from agent import Agent
    from memory import ExperienceStore
    mem = ExperienceStore(path=":memory:")
    ag = Agent(_fake_env(), mem, seed=1, journal_dir=td)
    # Constructor already loads the journal — that is the contract: an agent
    # starts with hints from its previous run.
    assert "spin:return_to_giver" in ag.policy.hints
    # refresh_hints() re-reads it (idempotent here) and returns the dict.
    assert ag.refresh_hints() == ag.policy.hints
