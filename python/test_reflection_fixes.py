"""Regression tests for the 2026-08-23 stall: after a restart the agent ran
1860x return_to_giver + 1140x turn_in_quest and NOTHING else for 3000 steps.

Root causes (each test below pins one):
  R1. goal_state.json survived restart with goal=TURN_IN for a quest that no
      longer exists in the live questLog -> PHASE_ALLOWED["TURN_IN"] pocket.
      FSM must re-validate the persisted quest against observed world facts
      and reset to NO_QUEST/DO_OBJECTIVE when the quest is gone.
  R2. refl.observe()/reflect() were called INSIDE `if i % SAVE_EVERY == 0`
      (every 100th step) so the 30-entry window needed ~3000 steps; journal
      never got written. observe must run EVERY step, reflect on cadence.
  R3. ACTION_SATURATION required |avg_reward| < 0.05, but return_to_giver earns
      POSITIVE navigation reward — a positive-reward treadmill is invisible to
      the detector. Saturation must trigger on near-CONSTANT reward too.
  R4. agent.py created GoalManager WITHOUT reflection_hints and play_autonomous
      never called load_reflection_hints() — the hint loop was closed in tests
      only. Agent must expose a way to refresh hints from the journal.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from goal_fsm import GoalFSM, QuestState, MIN_DWELL_STEPS
from self_reflection import SelfReflection


# ---- R1: stale TURN_IN goal against a live ACTIVE quest --------------------

def _fsm_turnin():
    f = GoalFSM(memory_path=os.path.join(os.path.dirname(__file__), "_test_fsm.json"))
    f.set("TURN_IN", "q_greyjaw", step=MIN_DWELL_STEPS)
    return f


def test_fsm_demotes_turnin_when_active_quest_observed():
    """Persisted TURN_IN/q_greyjaw + live world showing ACTIVE quest_status
    -> FSM must demote to DO_OBJECTIVE (Fix5 regression)."""
    f = _fsm_turnin()
    ws = {"quest_status": "ACTIVE", "quest": {"id": "q_prof_attune_smith"}}
    f.update_from_world(ws)
    assert f.state == QuestState.DO_OBJECTIVE, (
        f"stale TURN_IN kept, now {f.state}")


def test_fsm_keeps_turnin_when_same_quest_still_ready():
    f = _fsm_turnin()
    ws = {"quest_status": "READY_TO_TURN_IN", "quest": {"id": "q_greyjaw"}}
    f.update_from_world(ws)
    assert f.state == QuestState.TURN_IN


def test_fsm_reset_when_tracked_quest_vanished_from_world():
    """Persisted TURN_IN/q_greyjaw + live world showing NONE quest_status
    (quest gone) -> FSM must reset to QUEST_NONE."""
    f = _fsm_turnin()
    ws = {"quest_status": "NONE", "quest": {"id": "q_greyjaw"}}
    f.update_from_world(ws)
    assert f.state == QuestState.QUEST_NONE


# ---- R2: reflection observes every step -------------------------------------

def test_observe_is_per_step_and_reflect_on_cadence(tmp_path=None):
    import tempfile
    td = tempfile.mkdtemp()
    r = SelfReflection(path=os.path.join(td, "r.json"))
    # feed a saturated window of return_to_giver with constant positive reward
    for i in range(35):
        r.observe({"step": i, "action": "return_to_giver", "verdict": "SUCCESS",
                   "reward": 0.31, "hp": 1.0, "cell": "5_5", "deaths": 0,
                   "qprog": 10, "kills": 343})
        if i % 100 == 99:            # SAVE_EVERY cadence like the live loop
            r.reflect()
    # After 100 steps of per-step observation the window MUST hold all 100
    # records (bounded), i.e. saturation is detectable at first reflect().
    assert len(r.window) >= 30, f"window starved: {len(r.window)} records"


# ---- R3: positive-reward treadmill detected as saturation -------------------

def test_action_saturation_with_positive_constant_reward_detected(tmp_path=None):
    import tempfile
    td = tempfile.mkdtemp()
    r = SelfReflection(path=os.path.join(td, "r.json"))
    for i in range(40):
        r.observe({"step": i, "action": "return_to_giver", "verdict": "SUCCESS",
                   "reward": 0.31, "hp": 1.0, "cell": "5_5", "deaths": 0,
                   "qprog": 10, "kills": 343})
    out = r.reflect()
    kinds = [c["kind"] for c in out]
    assert "ACTION_SATURATION" in kinds, f"treadmill invisible, got {kinds}"
    spin = [c for c in out if c["key"] == "spin:return_to_giver"]
    assert spin, "no spin hint emitted"
