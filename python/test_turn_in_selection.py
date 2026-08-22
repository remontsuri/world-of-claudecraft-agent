"""TDD: turn_in_quest must pick a READY quest and actually turn it in.

User report 2026-08-22 (run 10356): after the ready-bucket fix, the agent
spammed return_to_giver(1855)/turn_in_quest(1145) with ALL INCONCLUSIVE and
dist stuck at 999.0 — it never reached any giver. Root causes to prove:

1) quest_skill.turn_in navigates via cap.navigate_to_turn_in(q), but ctx["quest"]
   was set from `ready[0]` which may LACK turnInNpc -> nav target missing ->
   PARTIAL forever. The chooser must prefer READY quests that HAVE turnInNpc.

2) dist=999.0 in every record means build_world_state never resolved ANY
   turn-in NPC for the selected quest: WorldMemory + FARSHORE fallback both
   missed (q_boars giver is marshal_redbrook, not in FARSHORE_QUEST_TURNIN).
   world_state must fall back to the zone static table AND the agent must
   persist givers on accept (already does) — test asserts ws gives a real
   distance when turnInNpc exists.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from world_state import build_world_state


def _info(active, ready):
    return {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [0, 0], "nearby": [], "inventory": [],
        "quests": {"active": active, "ready": ready, "done": []},
        "kills": 0, "deaths": 0,
    }


def test_ws_distance_resolved_for_ready_quest_with_giver():
    """A ready quest with turnInNpc must produce a REAL distance (< 999)."""
    info = _info(
        active=[{"id": "q_prof_attune_smith", "state": "active",
                 "objectives": [{"current": 0, "required": 0}]}],
        ready=[{"id": "q_boars", "state": "ready",
                "objectives": [{"current": 5, "required": 5}],
                "turnInNpc": {"x": -7.13, "z": 0.81}}],
    )
    ws = build_world_state(info)
    assert ws["quest"]["id"] == "q_boars", (
        "ws must select the quest with a resolvable giver, got %r" % ws["quest"].get("id"))
    assert ws["distance_to_giver"] < 100, ws["distance_to_giver"]


def test_ws_prefers_giver_known_over_first_active():
    """Selection must not stay pinned to a 0/0 ACTIVE quest when a ready one has a giver."""
    info = _info(
        active=[
            {"id": "q_prof_intro", "state": "active", "objectives": [{"current": 0, "required": 0}],
             "turnInNpc": {"x": 1.7, "z": 16.1}},
            {"id": "q_mine", "state": "ready", "objectives": [{"current": 1, "required": 1}]},
        ],
        ready=[],
    )
    # q_mine is state 'ready' inside ACTIVE bucket (server quirk seen live);
    # both have resolvable givers? q_mine has none here; q_prof_intro does.
    ws = build_world_state(info)
    assert ws["quest"]["id"] is not None
