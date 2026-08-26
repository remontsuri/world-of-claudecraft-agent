"""TDD tests for the Extended Replay Buffer (Task 8).

A transition must carry the FULL autonomy context, not just
(state, action, reward). Per the task spec each transition holds:

    state, action, next_state, reward, goal, subgoal, skill,
    skill_result (SUCCESS/FAILURE/NO_OP), failure_reason,
    progress_delta (detect_progress output), episode_id, timestamp.

These tests are written FIRST and must FAIL until python/replay.py
(and the memory.py wiring) is implemented.
"""

import json
import os
import time

from replay import create_transition, ExtendedReplayBuffer
from progress import detect_progress, classify_outcome


def _isolated_path(tmp_path):
    """A fresh, non-existent file path so buffers never load stale data."""
    return os.path.join(str(tmp_path), "replay_test.json")


# (a) create_transition returns ALL the required fields ----------------------
def test_create_transition_has_all_fields():
    t = create_transition(
        state={"hp_frac": 1.0},
        action="farm",
        next_state={"hp_frac": 1.0},
        reward=1.0,
        goal="kill 3 wolves",
        subgoal="approach wolf",
        skill="farm",
        episode_id="ep1",
        timestamp=1234.5,
        before_obs={"player": {"xp": 0}},
        after_obs={"player": {"xp": 10}},
    )
    required = (
        "state", "action", "next_state", "reward",
        "goal", "subgoal", "skill", "skill_result",
        "failure_reason", "progress_delta", "episode_id", "timestamp",
    )
    for key in required:
        assert key in t, f"transition missing field {key!r}"
    # sanity: the values we passed are preserved
    assert t["state"] == {"hp_frac": 1.0}
    assert t["action"] == "farm"
    assert t["reward"] == 1.0
    assert t["goal"] == "kill 3 wolves"
    assert t["subgoal"] == "approach wolf"
    assert t["skill"] == "farm"
    assert t["episode_id"] == "ep1"
    assert t["timestamp"] == 1234.5


# (b) skill_result is derived from classify_outcome when not explicit --------
def test_skill_result_from_classify_outcome():
    before = {"player": {"xp": 0}}
    after = {"player": {"xp": 5}}  # xp_delta>0 -> SUCCESS
    t = create_transition(state={}, action="farm", next_state={}, reward=0,
                          before_obs=before, after_obs=after)
    expected = classify_outcome(detect_progress(before, after))
    assert expected == "SUCCESS"
    assert t["skill_result"] == expected

    # an explicit override must win over the derived value
    t2 = create_transition(state={}, action="farm", next_state={}, reward=0,
                           skill_result="FAILURE",
                           before_obs=before, after_obs=after)
    assert t2["skill_result"] == "FAILURE"


# (c) progress_delta is exactly the detect_progress output -------------------
def test_progress_delta_is_detect_output():
    before = {"player": {"xp": 1}, "world": {"kills": 0}}
    after = {"player": {"xp": 9}, "world": {"kills": 1}}
    t = create_transition(state={}, action="x", next_state={}, reward=0,
                          before_obs=before, after_obs=after)
    assert t["progress_delta"] == detect_progress(before, after)


# (d) episode_id stays stable within an episode, changes on a new one --------
def test_episode_id_stable_within_episode_changes_on_new(tmp_path):
    buf = ExtendedReplayBuffer(cap=100, path=_isolated_path(tmp_path))
    buf.start_episode()
    eid1 = buf.episode_id
    assert eid1 is not None

    buf.add_transition(state={}, action="farm", next_state={}, reward=0,
                       before_obs={"player": {"xp": 0}},
                       after_obs={"player": {"xp": 1}})
    t1 = buf.buffer[-1]
    assert t1["episode_id"] == eid1

    # second transition in the SAME episode keeps the same id
    buf.add_transition(state={}, action="farm", next_state={}, reward=0,
                       before_obs={"player": {"xp": 1}},
                       after_obs={"player": {"xp": 2}})
    assert buf.buffer[-1]["episode_id"] == eid1

    # a new episode gets a DIFFERENT id and is stamped onto new transitions
    buf.start_episode()
    eid2 = buf.episode_id
    assert eid2 != eid1
    buf.add_transition(state={}, action="farm", next_state={}, reward=0,
                       before_obs={"player": {"xp": 0}},
                       after_obs={"player": {"xp": 1}})
    assert buf.buffer[-1]["episode_id"] == eid2


# (e) appending respects maxlen (old transitions evicted) --------------------
def test_buffer_respects_maxlen(tmp_path):
    buf = ExtendedReplayBuffer(cap=3, path=_isolated_path(tmp_path))
    for i in range(5):
        buf.add_transition(state={"i": i}, action="farm", next_state={},
                           reward=0.0,
                           before_obs={"player": {"xp": 0}},
                           after_obs={"player": {"xp": 1}})
    assert len(buf) == 3
    # the oldest two (i=0, i=1) have been evicted; newest three remain
    seen = [t["state"].get("i") for t in buf.buffer]
    assert seen == [2, 3, 4]


# (f) transition round-trips through JSON identically ------------------------
def test_transition_json_roundtrip():
    t = create_transition(
        state={"hp_frac": 0.5, "pos": [1, 2]},
        action="turn_in_quest",
        next_state={"hp_frac": 0.6, "pos": [3, 4]},
        reward=-0.5,
        goal="g", subgoal="sg", skill="turn_in_quest",
        episode_id="ep7", timestamp=time.time(),
        before_obs={"player": {"xp": 0, "deaths": 0}},
        after_obs={"player": {"xp": 3, "deaths": 0}},
    )
    raw = json.dumps(t, sort_keys=True)
    back = json.loads(raw)
    assert back == t


# (g) query helpers: last_failures(skill) and success_rate(skill) ------------
def test_last_failures_and_success_rate(tmp_path):
    buf = ExtendedReplayBuffer(cap=100, path=_isolated_path(tmp_path))
    buf.start_episode()
    # 3 SUCCESS + 1 FAILURE for "farm"
    buf.add_transition(state={}, action="farm", next_state={}, reward=1.0,
                       skill="farm",
                       before_obs={"player": {"xp": 0}, "world": {"kills": 0}},
                       after_obs={"player": {"xp": 5}, "world": {"kills": 1}})
    buf.add_transition(state={}, action="farm", next_state={}, reward=1.0,
                       skill="farm",
                       before_obs={"player": {"xp": 5}, "world": {"kills": 1}},
                       after_obs={"player": {"xp": 9}, "world": {"kills": 2}})
    buf.add_transition(state={}, action="farm", next_state={}, reward=-5.0,
                       skill="farm",
                       before_obs={"player": {"deaths": 0}},
                       after_obs={"player": {"deaths": 1}})  # death -> FAILURE
    # 1 SUCCESS for a different skill
    buf.add_transition(state={}, action="heal", next_state={}, reward=0.5,
                       skill="heal",
                       before_obs={"player": {"hp_fraction": 0.2}},
                       after_obs={"player": {"hp_fraction": 0.8}})

    # success_rate("farm") == 2 successes / 3 total == 0.666...
    assert abs(buf.success_rate("farm") - (2 / 3)) < 1e-9
    # unknown skill -> 0.0, not a crash
    assert buf.success_rate("never_used") == 0.0

    fails = buf.last_failures("farm")
    assert len(fails) == 1
    assert fails[0]["skill_result"] == "FAILURE"
    assert fails[0]["skill"] == "farm"

    # failures for an unrelated skill are not returned
    assert buf.last_failures("heal") == []


# (g extra) failure_reason is derived from verify_postconditions ------------
def test_failure_reason_derived_from_contract():
    # farm contract postcondition is kills_increased; a death with no kill
    # should yield a derived failure_reason naming the missing postcondition.
    before = {"player": {"deaths": 0}, "world": {"kills": 0}}
    after = {"player": {"deaths": 1}, "world": {"kills": 0}}
    t = create_transition(state={}, action="farm", next_state={}, reward=-5.0,
                          skill="farm", before_obs=before, after_obs=after)
    assert t["skill_result"] == "FAILURE"
    assert t["failure_reason"] == "kills_increased"
