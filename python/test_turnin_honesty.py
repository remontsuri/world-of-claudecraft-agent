"""Fix2 regression: a REJECTED turn-in must be a FAILURE, not INCONCLUSIVE.

2026-08-23 probe (scripts/_probe_turnin_watch.cjs): sim.turnInQuest on a ready
quest with no turn-in NPC nearby sends the command; the server silently rejects
it — NO error event reaches the client, the quest stays 'ready'. The old
verifier returned 'inconclusive' (reward 0), so blind turn-in spam was FREE:
measured run had 350x turn_in_quest all INCONCLUSIVE. A rejected attempt left
the world unchanged -> that is a failure of the attempted action (-0.3), which
the policy can finally learn to avoid.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from verifiers_py import verify_quest_turn_in


def _ctx(qlog_before, qlog_after, before_done=None, after_done=None,
         handle="q_prof_workorder_kitchens"):
    def _info(qlog):
        active = [q for q in (qlog or []) if q.get("state") == "active"]
        ready = [q for q in (qlog or []) if q.get("state") == "ready"]
        return {"quests": {"active": active, "ready": ready,
                           "done": list(before_done or [])}}
    return {
        "handle": handle,
        "before": _info(qlog_before),
        "after": _info(qlog_after),
    }


_Q = {"id": "q_prof_workorder_kitchens", "state": "ready",
      "objectives": [{"current": 8, "required": 8}], "turnInNpc": None}


def test_rejected_turnin_is_failure():
    """Quest ready before, STILL ready after (server rejected): failure."""
    c = _ctx([_Q], [_Q])
    assert verify_quest_turn_in(c) == "failure"


def test_successful_turnin_still_success():
    """Quest ready before, gone from ready and present in done after: success."""
    after_done = ["q_prof_workorder_kitchens"]
    c = _ctx([_Q], [], after_done=after_done)
    # simulate done list living under quests.done in BOTH snapshots
    c["before"]["quests"]["done"] = []
    c["after"]["quests"]["done"] = after_done
    assert verify_quest_turn_in(c) == "success"


def test_missing_before_info_stays_inconclusive():
    """No quest-log evidence at all -> cannot judge: inconclusive."""
    c = {"handle": "q_x", "before": {"quests": {}}, "after": {"quests": {}}}
    assert verify_quest_turn_in(c) == "inconclusive"


def test_active_untouched_by_turnin_is_failure():
    """Attempted turn-in on an ACTIVE (not ready) quest that stayed active:
    also a rejected attempt."""
    qa = {"id": "q_prof_attune_smith", "state": "active",
          "objectives": [{"current": 0, "required": 3}], "turnInNpc": None}
    c = _ctx([qa], [qa], handle="q_prof_attune_smith")
    assert verify_quest_turn_in(c) == "failure"
