"""Fix3 regression: turn-in must navigate using the REMEMBERED giver position.

2026-08-23 live snapshot: every quest in questLog reports `turnInNpc: null`,
so QuestCapability.navigate_to_turn_in returned FAILURE before moving a step
and turn_in_quest degraded to PARTIAL forever. WorldMemory already persists
giver positions per quest id (world_memory.json, hits=2335 in one run) —
turn_in_quest must backfill turnInNpc from there.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from memory import WorldMemory


class FakeBase:
    def __init__(self):
        self.turnin_calls = []

    def turn_in_quest(self, qid):
        self.turnin_calls.append(qid)
        return {"quests": {"active": [], "ready": [], "done": [qid]}}


class FakeEnv:
    """Mimics the BrowserEnv surface QuestCapability touches."""

    def __init__(self, nav_target_ok=True):
        self.base = FakeBase()
        self._last_info = {
            "player": {"hp": 120, "maxHp": 120},
            "nearby": [],
            "quests": {
                "active": [{"id": "q_a", "state": "active",
                            "objectives": [{"current": 0, "required": 3}],
                            "turnInNpc": None}],
                "ready": [{"id": "q_ready", "state": "ready",
                           "objectives": [{"current": 8, "required": 8}],
                           "turnInNpc": None}],
                "done": [],
            },
        }
        self.nav_calls = []
        self._nav_ok = nav_target_ok

    def _navigate_to_coord(self, x, z, max_steps=80):
        self.nav_calls.append((x, z))
        return self._nav_ok

    def _navigate_along_path(self, path, max_steps_per_leg=80):
        raise AssertionError("navPath not expected in this test")


def _world_mem_with(quest_id, x, z, tmpdir):
    import json
    p = os.path.join(tmpdir, "wm.json")
    wm = WorldMemory(path=p)
    wm.quest_givers[quest_id] = {
        "giver_id": "12", "giver_pos": {"x": x, "z": z},
        "zone": "farshore", "last_seen": 0.0,
    }
    wm.save()
    return wm


def test_turnin_backfills_nav_from_world_memory(tmp_path=None):
    import tempfile
    td = tempfile.mkdtemp()
    wm = _world_mem_with("q_ready", -16.59, -1.4, td)
    env = FakeEnv()

    from quest_skill import turn_in_quest
    res = turn_in_quest(env, {}, world_mem=wm)

    assert env.nav_calls, "never navigated — turnInNpc not backfilled from memory"
    # navigated toward the REMEMBERED position, not (0,0)
    assert env.nav_calls[-1] == (-16.59, -1.4), f"wrong target {env.nav_calls[-1]}"
    assert res == "SUCCESS"
    assert env.base.turnin_calls == ["q_ready"]


def test_turnin_without_memory_stays_partial(tmp_path=None):
    import tempfile
    td = tempfile.mkdtemp()
    wm = WorldMemory(path=os.path.join(td, "wm.json"))  # empty memory
    env = FakeEnv()

    from quest_skill import turn_in_quest
    res = turn_in_quest(env, {}, world_mem=wm)

    assert env.nav_calls == []
    assert res in ("PARTIAL", "FAILURE")
