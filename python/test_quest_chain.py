"""test_quest_chain.py — Unit and integration tests for the quest E2E chain.

Tests the full lifecycle: discover -> accept -> objective -> combat -> turn-in -> next.
"""
import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(__file__))

from goal_fsm import GoalFSM, QuestState
from quest_objective import ObjectiveType, Objective, resolve_objective, resolve_target, dispatch_objective
from quest_chaining import find_next_quest, filter_done_quests, select_best_quest
from quest_chain import QuestChain, ChainResult


# ============================================================================
# quest_objective tests
# ============================================================================

def test_resolve_objective_kill():
    """resolve_objective returns KILL objective for a kill quest."""
    quest = {
        "id": "q1",
        "objectives": [
            {"type": "kill", "targetMobId": "wolf", "current": 3, "required": 5}
        ]
    }
    obj = resolve_objective(quest)
    assert obj is not None
    assert obj.type == ObjectiveType.KILL
    assert obj.target_mob_id == "wolf"
    assert obj.current == 3
    assert obj.required == 5


def test_resolve_objective_collect():
    """resolve_objective returns COLLECT objective for a collect quest."""
    quest = {
        "id": "q2",
        "objectives": [
            {"type": "collect", "itemId": "pelt", "current": 0, "required": 3}
        ]
    }
    obj = resolve_objective(quest)
    assert obj is not None
    assert obj.type == ObjectiveType.COLLECT
    assert obj.item_id == "pelt"


def test_resolve_objective_gather():
    """resolve_objective returns GATHER objective for a gather quest."""
    quest = {
        "id": "q3",
        "objectives": [
            {"type": "gather", "nodeType": "herb", "current": 1, "required": 4,
             "toolItemId": "herb_knife"}
        ]
    }
    obj = resolve_objective(quest)
    assert obj is not None
    assert obj.type == ObjectiveType.GATHER
    assert obj.node_type == "herb"
    assert obj.tool_item_id == "herb_knife"


def test_resolve_objective_all_complete():
    """resolve_objective returns None when all objectives are complete."""
    quest = {
        "id": "q4",
        "objectives": [
            {"type": "kill", "targetMobId": "wolf", "current": 5, "required": 5}
        ]
    }
    obj = resolve_objective(quest)
    assert obj is None


def test_resolve_objective_skips_complete():
    """resolve_objective skips complete objectives and returns the first incomplete."""
    quest = {
        "id": "q5",
        "objectives": [
            {"type": "kill", "targetMobId": "wolf", "current": 5, "required": 5},
            {"type": "collect", "itemId": "pelt", "current": 1, "required": 3}
        ]
    }
    obj = resolve_objective(quest)
    assert obj is not None
    assert obj.type == ObjectiveType.COLLECT
    assert obj.item_id == "pelt"


def test_resolve_objective_unknown_type_defaults_to_kill():
    """resolve_objective defaults to KILL for unknown objective types."""
    quest = {
        "id": "q6",
        "objectives": [
            {"type": "unknown_type", "current": 0, "required": 1}
        ]
    }
    obj = resolve_objective(quest)
    assert obj is not None
    assert obj.type == ObjectiveType.KILL


def test_resolve_target_kill():
    """resolve_target finds the target mob for a KILL objective."""
    objective = Objective(type=ObjectiveType.KILL, target_mob_id="wolf", current=0, required=5)
    info = {
        "nearby": [
            {"kind": "mob", "templateId": "rabbit", "dist": 5},
            {"kind": "mob", "templateId": "wolf", "dist": 10},
        ]
    }
    target = resolve_target(objective, info)
    assert target is not None
    assert target["templateId"] == "wolf"


def test_resolve_target_kill_fallback():
    """resolve_target falls back to any hostile mob when target not found."""
    objective = Objective(type=ObjectiveType.KILL, target_mob_id="bear", current=0, required=5)
    info = {
        "nearby": [
            {"kind": "mob", "templateId": "rabbit", "dist": 5, "hostile": True},
        ]
    }
    target = resolve_target(objective, info)
    assert target is not None
    assert target["templateId"] == "rabbit"


def test_resolve_target_gather():
    """resolve_target finds the gather node for a GATHER objective."""
    objective = Objective(type=ObjectiveType.GATHER, node_type="herb", current=0, required=3)
    info = {
        "nearby": [
            {"kind": "node", "nodeType": "ore", "dist": 5},
            {"kind": "node", "nodeType": "herb", "dist": 10},
        ]
    }
    target = resolve_target(objective, info)
    assert target is not None
    assert target["nodeType"] == "herb"


def test_resolve_target_no_target():
    """resolve_target returns None when no matching target is found."""
    objective = Objective(type=ObjectiveType.KILL, target_mob_id="dragon", current=0, required=1)
    info = {"nearby": []}
    target = resolve_target(objective, info)
    assert target is None


# ============================================================================
# quest_chaining tests
# ============================================================================

def test_filter_done_quests_excludes_done():
    """filter_done_quests excludes NPCs where all quests are done."""
    npcs = [
        {"id": "npc1", "questIds": ["q1", "q2"]},
        {"id": "npc2", "questIds": ["q3"]},
    ]
    done_ids = {"q1", "q2"}
    result = filter_done_quests(npcs, done_ids)
    assert len(result) == 1
    assert result[0]["id"] == "npc2"


def test_filter_done_quests_all_done():
    """filter_done_quests returns empty list when all quests are done."""
    npcs = [
        {"id": "npc1", "questIds": ["q1"]},
    ]
    done_ids = {"q1"}
    result = filter_done_quests(npcs, done_ids)
    assert len(result) == 0


def test_filter_done_quests_none_done():
    """filter_done_quests returns all NPCs when no quests are done."""
    npcs = [
        {"id": "npc1", "questIds": ["q1", "q2"]},
        {"id": "npc2", "questIds": ["q3"]},
    ]
    done_ids = set()
    result = filter_done_quests(npcs, done_ids)
    assert len(result) == 2


def test_select_best_quest_closest():
    """select_best_quest selects the closest NPC."""
    givers = [
        {"id": "npc1", "dist": 20, "_available_quests": ["q1"]},
        {"id": "npc2", "dist": 5, "_available_quests": ["q2"]},
    ]
    result = select_best_quest(givers)
    assert result is not None
    assert result["npc"]["id"] == "npc2"
    assert result["quest_id"] == "q2"


def test_select_best_quest_empty():
    """select_best_quest returns None for empty list."""
    result = select_best_quest([])
    assert result is None


def test_find_next_quest_excludes_done():
    """find_next_quest excludes done quests."""
    info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "questIds": ["q1", "q2"]},
        ]
    }
    done_ids = {"q1"}
    result = find_next_quest(info, done_ids)
    assert result is not None
    assert result["quest_id"] == "q2"


def test_find_next_quest_all_done():
    """find_next_quest returns None when all quests are done."""
    info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "questIds": ["q1"]},
        ]
    }
    done_ids = {"q1"}
    result = find_next_quest(info, done_ids)
    assert result is None


def test_find_next_quest_no_npcs():
    """find_next_quest returns None when no NPCs are nearby."""
    info = {"nearby": []}
    result = find_next_quest(info, set())
    assert result is None


# ============================================================================
# goal_fsm K6 extensions tests
# ============================================================================

def test_fsm_done_ids_persist():
    """FSM done_ids persist across save/load."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "fsm.json")
        f = GoalFSM(memory_path=path)
        f.done_ids.add("q1")
        f.done_ids.add("q2")
        f.current_objective_idx = 2
        f.save()

        f2 = GoalFSM(memory_path=path)
        assert "q1" in f2.done_ids
        assert "q2" in f2.done_ids
        assert f2.current_objective_idx == 2


def test_fsm_record_quest_done():
    """record_quest_done adds quest ID to done_ids."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "fsm.json")
        f = GoalFSM(memory_path=path)
        f.record_quest_done("q1")
        assert "q1" in f.done_ids
        f.record_quest_done("q2")
        assert "q2" in f.done_ids


def test_fsm_get_next_objective():
    """get_next_objective returns the first incomplete objective."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "fsm.json")
        f = GoalFSM(memory_path=path)
        f.active_quest = {
            "id": "q1",
            "objectives": [
                {"type": "kill", "current": 5, "required": 5},
                {"type": "collect", "current": 1, "required": 3},
            ]
        }
        obj = f.get_next_objective()
        assert obj is not None
        assert obj["type"] == "collect"
        assert obj["current"] == 1


def test_fsm_get_next_objective_all_complete():
    """get_next_objective returns None when all objectives are complete."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "fsm.json")
        f = GoalFSM(memory_path=path)
        f.active_quest = {
            "id": "q1",
            "objectives": [
                {"type": "kill", "current": 5, "required": 5},
            ]
        }
        obj = f.get_next_objective()
        assert obj is None


def test_fsm_done_ids_not_cleared_on_reset():
    """FSM reset does NOT clear done_ids (they persist across quests)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "fsm.json")
        f = GoalFSM(memory_path=path)
        f.done_ids.add("q1")
        f.reset()
        assert "q1" in f.done_ids


def test_fsm_update_from_world_done_adds_to_done_ids():
    """FSM update_from_world with DONE status adds quest ID to done_ids."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "fsm.json")
        f = GoalFSM(memory_path=path)
        f.active_quest = {"id": "q1"}
        f.update_from_world({"quest_status": "DONE", "quest": {"id": "q1"}})
        assert f.state == QuestState.DONE
        assert "q1" in f.done_ids


# ============================================================================
# quest_chain integration tests
# ============================================================================

class MockEnv:
    """Minimal mock of BrowserEnv for testing QuestChain."""
    def __init__(self, info):
        self._last_info = info
        self.step_calls = []

    def step(self, idx, ctx=None):
        self.step_calls.append((idx, ctx))

    def _navigate_to_coord(self, x, z, max_steps=80):
        return True


class MockAgent:
    """Minimal mock of Agent for testing QuestChain."""
    def __init__(self, env):
        self.env = env
        self.done_ids = set()
        self.world_mem = None


def test_quest_chain_discover():
    """QuestChain.discover finds the best quest giver."""
    info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "questIds": ["q1", "q2"]},
            {"kind": "npc", "id": "npc2", "dist": 10, "questIds": ["q3"]},
        ]
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    result = qc.discover()
    assert result is not None
    assert result["npc"]["id"] == "npc1"
    assert result["quest_id"] == "q1"


def test_quest_chain_discover_filters_done():
    """QuestChain.discover filters out done quests."""
    info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "questIds": ["q1"]},
            {"kind": "npc", "id": "npc2", "dist": 10, "questIds": ["q2", "q3"]},
        ]
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    qc.done_ids = {"q1", "q2"}
    result = qc.discover()
    assert result is not None
    assert result["npc"]["id"] == "npc2"
    assert result["quest_id"] == "q3"


def test_quest_chain_resolve_objective():
    """QuestChain.resolve_objective returns the first incomplete objective."""
    info = {
        "nearby": [
            {"kind": "mob", "templateId": "wolf", "dist": 10},
        ]
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    quest = {
        "id": "q1",
        "objectives": [
            {"type": "kill", "targetMobId": "wolf", "current": 3, "required": 5}
        ]
    }
    obj = qc.resolve_objective(quest)
    assert obj is not None
    assert obj.type == ObjectiveType.KILL
    assert obj.target_mob_id == "wolf"


def test_quest_chain_resolve_target():
    """QuestChain.resolve_target finds the target entity."""
    info = {
        "nearby": [
            {"kind": "mob", "templateId": "wolf", "dist": 10},
        ]
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    objective = Objective(type=ObjectiveType.KILL, target_mob_id="wolf", current=0, required=5)
    target = qc.resolve_target(objective)
    assert target is not None
    assert target["templateId"] == "wolf"


def test_quest_chain_verify_progress_incomplete():
    """QuestChain.verify_progress returns False for incomplete quest."""
    info = {
        "quests": {
            "active": [{"id": "q1", "objectives": [{"current": 3, "required": 5}]}],
            "ready": [],
        }
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    quest = {"id": "q1", "objectives": [{"current": 3, "required": 5}]}
    assert qc.verify_progress(quest) is False


def test_quest_chain_verify_progress_complete():
    """QuestChain.verify_progress returns True for complete quest."""
    info = {
        "quests": {
            "active": [{"id": "q1", "objectives": [{"current": 5, "required": 5}]}],
            "ready": [],
        }
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    quest = {"id": "q1", "objectives": [{"current": 5, "required": 5}]}
    assert qc.verify_progress(quest) is True


def test_quest_chain_run_chain_no_quest_discover():
    """QuestChain.run_chain discovers a quest when none active."""
    info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "x": 10, "z": 20, "questIds": ["q1"]},
        ],
        "quests": {"active": [], "ready": []},
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    # Mock accept_and_verify to return True
    qc.accept_and_verify = lambda giver, qid: True
    result = qc.run_chain()
    assert result.verdict == "SUCCESS"
    assert result.action == "accept_quest"


def test_quest_chain_run_chain_active_quest_objective():
    """QuestChain.run_chain resolves objective when quest is active."""
    info = {
        "nearby": [
            {"kind": "mob", "templateId": "wolf", "dist": 10},
        ],
        "quests": {
            "active": [{"id": "q1", "objectives": [{"type": "kill", "targetMobId": "wolf", "current": 3, "required": 5}]}],
            "ready": [],
        }
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    result = qc.run_chain()
    assert result.action == "execute_objective"
    assert result.quest_id == "q1"


def test_quest_chain_run_chain_ready_to_turn_in():
    """QuestChain.run_chain turns in quest when ready."""
    info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "x": 10, "z": 20, "questIds": ["q1"]},
        ],
        "quests": {
            "active": [{"id": "q1", "objectives": [{"type": "kill", "current": 5, "required": 5}]}],
            "ready": [],
        }
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    qc.turn_in_and_verify = lambda quest: True
    result = qc.run_chain()
    assert result.verdict == "SUCCESS"
    assert result.action == "turn_in_quest"
    assert "q1" in qc.done_ids


def test_quest_chain_run_chain_discover_fails():
    """QuestChain.run_chain returns FAILURE when no quest giver found."""
    info = {
        "nearby": [],
        "quests": {"active": [], "ready": []},
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    result = qc.run_chain()
    assert result.verdict == "FAILURE"
    assert result.action == "discover"


# ============================================================================
# Full chain integration test
# ============================================================================

def test_full_quest_chain_kill_quest():
    """Full kill quest chain: discover -> accept -> objective -> turn-in -> next."""
    # Step 1: No quest, discover giver
    info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "x": 10, "z": 20, "questIds": ["q1", "q2"]},
        ],
        "quests": {"active": [], "ready": []},
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    qc.accept_and_verify = lambda giver, qid: True

    result = qc.run_chain()
    assert result.verdict == "SUCCESS"
    assert result.action == "accept_quest"
    assert result.quest_id == "q1"

    # Step 2: Quest active, resolve objective
    env._last_info = {
        "nearby": [
            {"kind": "mob", "templateId": "wolf", "dist": 10},
        ],
        "quests": {
            "active": [{"id": "q1", "objectives": [{"type": "kill", "targetMobId": "wolf", "current": 3, "required": 5}]}],
            "ready": [],
        }
    }
    result = qc.run_chain()
    assert result.action == "execute_objective"
    assert result.objective is not None
    assert result.objective.type == ObjectiveType.KILL

    # Step 3: Quest complete, turn in
    env._last_info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "x": 10, "z": 20, "questIds": ["q1", "q2"]},
        ],
        "quests": {
            "active": [{"id": "q1", "objectives": [{"type": "kill", "current": 5, "required": 5}]}],
            "ready": [],
        }
    }
    qc.turn_in_and_verify = lambda quest: True
    result = qc.run_chain()
    assert result.verdict == "SUCCESS"
    assert result.action == "turn_in_quest"
    assert "q1" in qc.done_ids

    # Step 4: Next quest (q1 is done, should get q2)
    env._last_info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "x": 10, "z": 20, "questIds": ["q1", "q2"]},
        ],
        "quests": {"active": [], "ready": []},
    }
    result = qc.run_chain()
    assert result.verdict == "SUCCESS"
    assert result.action == "accept_quest"
    assert result.quest_id == "q2"  # q1 is done, so q2 is selected


def test_quest_chain_no_reaccept_same_quest():
    """QuestChain never re-accepts a quest that is in done_ids."""
    info = {
        "nearby": [
            {"kind": "npc", "id": "npc1", "dist": 5, "x": 10, "z": 20, "questIds": ["q1"]},
        ],
        "quests": {"active": [], "ready": []},
    }
    env = MockEnv(info)
    agent = MockAgent(env)
    qc = QuestChain(agent, env)
    qc.done_ids = {"q1"}  # q1 already done

    result = qc.run_chain()
    # Should fail to discover since q1 is done
    assert result.verdict == "FAILURE"
    assert result.action == "discover"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
