"""TDD for giver-position resolver: static game truth must win over world_mem.

RED was documented separately (buggy inline logic returned 306.3,64.5).
GREEN: resolve_giver_pos (agent.py) returns (4.5, 5.5) even when world_mem lies.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import resolve_giver_pos

# Load the real static table so the test exercises actual game coordinates.
import json
with open(os.path.join(os.path.dirname(__file__), "giver_positions.json"), "r", encoding="utf-8") as _f:
    JSON_GIVERS = json.load(_f)

# world_mem holding STALE coords (observed: 306.3, 64.5 instead of 4.5, 5.5)
WORLD_MEM_LIE = type("WM", (), {"quest_givers": {"marshal_redbrook": {"giver_pos": {"x": 306.3, "z": 64.5}}}})()


def test_static_truth_beats_world_mem_lie():
    # giver_id given, but NOT in live nearby -> should resolve from json by exact id (4.5, 5.5),
    # NOT world_mem lie (306.3, 64.5)
    got = resolve_giver_pos(
        giver_id="marshal_redbrook",
        nearby=[],
        quest_giver=None,
        world_mem=WORLD_MEM_LIE,
        json_givers=JSON_GIVERS,
        player_pos=[2, -2],  # real Eastbrook start
    )
    assert got == (4.5, 5.5), f"expected static truth (4.5, 5.5), got {got}"


def test_live_nearby_wins():
    nearby = [{"id": "marshal_redbrook", "x": 4.5, "z": 5.5, "dist": 3.1}]
    got = resolve_giver_pos(
        giver_id="marshal_redbrook",
        nearby=nearby,
        quest_giver=None,
        world_mem=WORLD_MEM_LIE,
        json_givers=JSON_GIVERS,
        player_pos=[0, 0],
    )
    assert got == (4.5, 5.5), f"expected live snapshot (4.5, 5.5), got {got}"


if __name__ == "__main__":
    test_static_truth_beats_world_mem_lie()
    test_live_nearby_wins()
    print("GREEN: both resolver tests pass")
