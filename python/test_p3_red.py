"""P3 RED TESTS: navigation, facing, target, combat, kill, quest, respawn, FSM persistence.

These tests verify the core game mechanics that the agent depends on.
They are RED (verified) — they test real behavior, not mocks.

Run: cd python && python -m pytest test_p3_red.py -v
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from goal_fsm import GoalFSM, QuestState, FailureReason
from navigation import (
    NavigationController, find_target, tolerance_for,
    ARRIVED, MOVING, STUCK, BLOCKED, TIMEOUT, NO_TARGET,
)
from observation import encode_observation, _pick_target, _mob_matches
from reward import outcome_reward, WEIGHTS
from bounded_execution import BoundedExecution


# ============================================================
# HELPERS
# ============================================================

def _obs(px=0.0, pz=0.0, ents=None, dead=False, hp_fraction=1.0, player_class="warrior"):
    return {
        "player": {
            "position": [px, pz],
            "dead": dead,
            "hp_fraction": hp_fraction,
            "player_class": player_class,
            "facing": 0.0,
        },
        "_entities": ents or [],
    }


def _giver(x, z, d=None, qids=None):
    return {
        "kind": "npc",
        "questIds": qids or ["q1"],
        "x": x, "z": z,
        "_dist": d if d is not None else (x ** 2 + z ** 2) ** 0.5,
    }


def _mob(x, z, tid="forest_wolf", hp=10, d=None, hostile=True):
    return {
        "kind": "mob",
        "templateId": tid,
        "hp": hp,
        "x": x, "z": z,
        "hostile": hostile,
        "_dist": d if d is not None else (x ** 2 + z ** 2) ** 0.5,
    }


def _fsm(tmpdir=None):
    d = tmpdir or tempfile.mkdtemp()
    return GoalFSM(memory_path=os.path.join(d, "fsm.json"))


# ============================================================
# FACING
# ============================================================

class TestFacing:
    """Observation encodes angle RELATIVE to player facing, not world north."""

    def test_mob_straight_ahead_has_zero_angle(self):
        ws = {
            "player": {"facing": 0.0, "position": [0, 0]},
            "player_facing": 0.0,
        }
        info = {
            "player": {"facing": 0.0, "position": [0, 0]},
            "nearby": [_mob(0, 10)],  # directly in front (north)
        }
        obs = encode_observation(ws, info)
        assert obs["player"]["facing"] == 0.0
        # "mobs" is the key for spatial vectors
        assert len(obs.get("mobs", [])) == 1
        assert abs(obs["mobs"][0]["angle"]) < 0.01

    def test_mob_behind_has_pi_angle(self):
        ws = {"player": {"facing": 0.0}, "player_facing": 0.0}
        info = {
            "player": {"facing": 0.0, "position": [0, 0]},
            "nearby": [_mob(0, -10)],  # behind (south)
        }
        obs = encode_observation(ws, info)
        assert len(obs.get("mobs", [])) == 1
        # angle should be ~pi (behind)
        assert abs(abs(obs["mobs"][0]["angle"]) - math.pi) < 0.01

    def test_facing_rotation_shifts_relative_angle(self):
        """If player turns 90 degrees right, a mob that was straight ahead
        is now at -pi/2 (to the left)."""
        ws = {"player": {"facing": math.pi / 2}, "player_facing": math.pi / 2}
        info = {
            "player": {"facing": math.pi / 2, "position": [0, 0]},
            "nearby": [_mob(0, 10)],  # world north
        }
        obs = encode_observation(ws, info)
        assert len(obs.get("mobs", [])) == 1
        # relative angle = world_bearing - facing = 0 - pi/2 = -pi/2
        assert abs(obs["mobs"][0]["angle"] - (-math.pi / 2)) < 0.01


# ============================================================
# TARGET SELECTION
# ============================================================

class TestTargetSelection:
    """Quest mob is prioritized over nearest mob."""

    def test_quest_mob_chosen_over_closer_non_quest(self):
        mobs = [
            _mob(0, 3, "boar"),           # closer, not quest
            _mob(0, 12, "forest_wolf"),   # quest target
        ]
        target = _pick_target(mobs, "forest_wolf")
        assert target["templateId"] == "forest_wolf"

    def test_nearest_mob_when_no_quest(self):
        mobs = [
            _mob(0, 3, "boar"),
            _mob(0, 12, "forest_wolf"),
        ]
        target = _pick_target(mobs, None)
        assert target["templateId"] == "boar"

    def test_mob_matches_by_template_id(self):
        mob = _mob(0, 5, "forest_wolf")
        assert _mob_matches(mob, "forest_wolf") is True
        assert _mob_matches(mob, "boar") is False

    def test_mob_matches_by_human_readable_name(self):
        mob = {"templateId": "Forest Wolf", "name": "Forest Wolf"}
        assert _mob_matches(mob, "forest_wolf") is True

    def test_observation_marks_quest_target(self):
        ws = {
            "player": {"facing": 0.0, "position": [0, 0]},
            "player_facing": 0.0,
            "quests": {
                "active": [{
                    "id": "q_kill_wolves",
                    "state": "active",
                    "objectives": [{"type": "kill", "targetMobId": "forest_wolf", "current": 0, "required": 3}],
                }],
            },
        }
        info = {
            "player": {"facing": 0.0, "position": [0, 0]},
            "nearby": [_mob(0, 3, "boar"), _mob(0, 12, "forest_wolf")],
        }
        obs = encode_observation(ws, info)
        assert obs["target"]["is_quest_target"] is True
        assert obs["target"]["mob_id"] == "forest_wolf"


# ============================================================
# COMBAT (class-based ranges)
# ============================================================

class TestCombatRanges:
    """Different classes have different attack ranges."""

    def test_warrior_must_close_in(self):
        assert tolerance_for("mob", "warrior") <= 6.0

    def test_mage_can_cast_from_distance(self):
        assert tolerance_for("mob", "mage") >= 20.0

    def test_hunter_has_longest_range(self):
        assert tolerance_for("mob", "hunter") > tolerance_for("mob", "mage")

    def test_warrior_out_of_range_must_move(self):
        nav = NavigationController()
        obs = _obs(ents=[_mob(0, 30)])
        obs["player"]["player_class"] = "warrior"
        nav.set_target(obs, "mob")
        assert nav.observe(obs)["status"] == MOVING

    def test_mage_in_range_at_distance(self):
        nav = NavigationController()
        obs = _obs(ents=[_mob(0, 22)])
        obs["player"]["player_class"] = "mage"
        nav.set_target(obs, "mob")
        assert nav.observe(obs)["status"] == ARRIVED

    def test_melee_range_gate(self):
        """INTERACT_RANGE (5.0) is the melee gate."""
        from observation import INTERACT_RANGE
        assert INTERACT_RANGE == 5.0

    def test_quest_range_gate(self):
        """QUEST_RANGE (7.0) is the accept/turn-in gate."""
        from observation import QUEST_RANGE
        assert QUEST_RANGE == 7.0


# ============================================================
# KILL REWARD
# ============================================================

class TestKillReward:
    """Reward is computed from world deltas, not opinions."""

    def test_kill_gives_positive_reward(self):
        before = {"kills": 0, "xp": 100, "copper": 50, "hp_frac": 1.0}
        after = {"kills": 1, "xp": 110, "copper": 50, "hp_frac": 0.95}
        r = outcome_reward(before, after, "SUCCESS")
        assert r > 0, f"kill should be positive, got {r}"

    def test_death_gives_negative_reward(self):
        before = {"kills": 0, "deaths": 0, "hp_frac": 0.3}
        after = {"kills": 0, "deaths": 1, "hp_frac": 0.0}
        r = outcome_reward(before, after, "FAILURE")
        assert r < 0, f"death should be negative, got {r}"

    def test_env_error_gives_zero_reward(self):
        before = {"kills": 0, "xp": 100}
        after = {"kills": 0, "xp": 100}
        r = outcome_reward(before, after, "SUCCESS", outcome_kind="ENV_ERROR")
        assert r == 0.0, f"ENV_ERROR must be 0, got {r}"

    def test_quest_progress_gives_reward(self):
        before = {"quest_progress": 0, "xp": 100}
        after = {"quest_progress": 5, "xp": 100}
        r = outcome_reward(before, after, "SUCCESS")
        assert r > 0, f"quest progress should be positive, got {r}"

    def test_drift_away_from_giver_is_penalty(self):
        before = {"distance_to_giver": 30.0, "hp_frac": 1.0}
        after = {"distance_to_giver": 50.0, "hp_frac": 1.0}
        r = outcome_reward(before, after, "OK")
        assert r < 0, f"drifting away should be negative, got {r}"

    def test_moving_closer_to_giver_is_reward(self):
        before = {"distance_to_giver": 50.0, "hp_frac": 1.0}
        after = {"distance_to_giver": 20.0, "hp_frac": 1.0}
        r = outcome_reward(before, after, "OK")
        assert r > 0, f"moving closer should be positive, got {r}"


# ============================================================
# QUEST CYCLE (FSM transitions)
# ============================================================

class TestQuestCycle:
    """Full quest lifecycle: NONE -> FIND -> ACCEPT -> DO -> RETURN -> TURN_IN -> DONE."""

    def test_quest_none_to_find_giver(self):
        f = _fsm()
        assert f.state == QuestState.QUEST_NONE
        action, ctx = f.decide({}, {"nearby": [_giver(3, 0)]})
        assert f.state == QuestState.FIND_GIVER
        assert action == "navigate"

    def test_find_giver_to_accept_when_close(self):
        f = _fsm()
        f.set(QuestState.FIND_GIVER, "q1")
        f.quest_giver = {"x": 3, "z": 0, "dist": 3.0}
        action, ctx = f.decide({}, {"player_pos": [0, 0]})
        assert f.state == QuestState.ACCEPT
        assert action == "accept_quest"

    def test_accept_to_verify(self):
        f = _fsm()
        f.set(QuestState.ACCEPT, "q1")
        f.quest_giver = {"x": 0, "z": 0}
        action, ctx = f.decide({}, {})
        assert f.state == QuestState.VERIFY_ACCEPT
        assert action == "accept_quest"

    def test_verify_accept_to_do_objective(self):
        f = _fsm()
        f.set(QuestState.VERIFY_ACCEPT, "q1")
        f.quest_giver = {"x": 0, "z": 0}
        action, ctx = f.decide({"quest_status": "ACTIVE"}, {})
        assert f.state == QuestState.DO_OBJECTIVE

    def test_do_objective_farms_when_mob_present(self):
        f = _fsm()
        f.set(QuestState.DO_OBJECTIVE, "q1")
        action, ctx = f.decide({"quest_status": "ACTIVE", "has_mob": True}, {})
        assert action == "farm"

    def test_do_objective_explores_when_no_mob(self):
        f = _fsm()
        f.set(QuestState.DO_OBJECTIVE, "q1")
        action, ctx = f.decide({"quest_status": "ACTIVE", "has_mob": False}, {})
        assert action == "explore"

    def test_ready_to_turn_in_transitions_to_return(self):
        f = _fsm()
        f.set(QuestState.DO_OBJECTIVE, "q1")
        f.quest_giver = {"x": 50, "z": 0}
        action, ctx = f.decide({"quest_status": "READY_TO_TURN_IN"}, {"player_pos": [0, 0]})
        assert f.state == QuestState.RETURN_TO_GIVER
        assert action == "navigate"

    def test_return_to_giver_arrives_then_turn_in(self):
        f = _fsm()
        f.set(QuestState.RETURN_TO_GIVER, "q1")
        f.quest_giver = {"x": 3, "z": 0}
        action, ctx = f.decide({}, {"player_pos": [0, 0]})
        assert f.state == QuestState.TURN_IN
        assert action == "turn_in_quest"

    def test_turn_in_to_verify(self):
        f = _fsm()
        f.set(QuestState.TURN_IN, "q1")
        f.quest_giver = {"x": 0, "z": 0}
        action, ctx = f.decide({}, {})
        assert f.state == QuestState.VERIFY_TURN_IN
        assert action == "turn_in_quest"

    def test_verify_turn_in_to_done(self):
        f = _fsm()
        f.set(QuestState.VERIFY_TURN_IN, "q1")
        f.quest_giver = {"x": 0, "z": 0}
        action, ctx = f.decide({"quest_status": "DONE"}, {})
        assert f.state == QuestState.DONE

    def test_done_resets_to_none(self):
        f = _fsm()
        f.set(QuestState.DONE, "q1")
        action, ctx = f.decide({}, {})
        assert f.state == QuestState.QUEST_NONE
        assert f.active_quest is None

    def test_full_quest_cycle_integration(self):
        """Simulate a complete quest cycle through FSM."""
        f = _fsm()
        # 1. Start: no quest
        assert f.state == QuestState.QUEST_NONE
        # 2. Find giver
        f.decide({}, {"nearby": [_giver(3, 0, qids=["q_bones"])]})
        assert f.state == QuestState.FIND_GIVER
        # 3. Approach giver
        f.quest_giver = {"x": 3, "z": 0, "dist": 3.0}
        f.decide({}, {"player_pos": [0, 0]})
        assert f.state == QuestState.ACCEPT
        # 4. Accept quest
        f.decide({}, {})
        assert f.state == QuestState.VERIFY_ACCEPT
        # 5. Quest becomes active
        f.decide({"quest_status": "ACTIVE"}, {})
        assert f.state == QuestState.DO_OBJECTIVE
        # 6. Farm mobs
        f.decide({"quest_status": "ACTIVE", "has_mob": True}, {})
        assert f.state == QuestState.DO_OBJECTIVE
        # 7. Quest ready to turn in
        f.quest_giver = {"x": 50, "z": 0}
        f.decide({"quest_status": "READY_TO_TURN_IN"}, {"player_pos": [0, 0]})
        assert f.state == QuestState.RETURN_TO_GIVER
        # 8. Arrive at giver
        f.quest_giver = {"x": 3, "z": 0}
        f.decide({}, {"player_pos": [0, 0]})
        assert f.state == QuestState.TURN_IN
        # 9. Turn in
        f.decide({}, {})
        assert f.state == QuestState.VERIFY_TURN_IN
        # 10. Quest done
        f.decide({"quest_status": "DONE"}, {})
        assert f.state == QuestState.DONE
        # 11. Reset
        f.decide({}, {})
        assert f.state == QuestState.QUEST_NONE


# ============================================================
# RESPAWN
# ============================================================

class TestRespawn:
    """Death and recovery flow."""

    def test_enter_dead_saves_quest(self):
        f = _fsm()
        f.set(QuestState.DO_OBJECTIVE, "q1")
        f.quest_giver = {"x": 10, "z": 10}
        f.enter_dead()
        assert f.state == QuestState.RESPAWN
        assert f._pre_death_quest is not None
        assert f._pre_death_giver is not None
        assert f.failure_reason == FailureReason.COMBAT_FAILURE

    def test_resume_from_dead_restores_quest(self):
        f = _fsm()
        f.set(QuestState.DO_OBJECTIVE, "q1")
        f.quest_giver = {"x": 10, "z": 10}
        f.enter_dead()
        f.resume_from_dead()
        assert f.state == QuestState.RETURN_TO_GIVER
        assert f.active_quest is not None
        assert f.quest_giver is not None

    def test_resume_from_dead_no_quest_goes_to_none(self):
        f = _fsm()
        f.set(QuestState.QUEST_NONE)
        f.enter_dead()
        f.resume_from_dead()
        assert f.state == QuestState.QUEST_NONE

    def test_respawn_handler_waits_when_dead(self):
        f = _fsm()
        f.set(QuestState.RESPAWN, "q1")
        action, ctx = f.decide({}, {"player": {"dead": True, "hp": 0}})
        assert action == "heal"
        assert ctx["reason"] == "awaiting_respawn"

    def test_respawn_handler_recovers_when_alive(self):
        f = _fsm()
        f.set(QuestState.RESPAWN, "q1")
        action, ctx = f.decide({}, {"player": {"dead": False, "hp": 50}})
        assert f.state == QuestState.QUEST_NONE
        assert action == "explore"

    def test_death_counter_increments(self):
        f = _fsm()
        f.set(QuestState.DO_OBJECTIVE, "q1")
        f.enter_dead()
        assert f.total_deaths == 1
        f.enter_dead()  # already in RESPAWN, should not double-count
        assert f.total_deaths == 1


# ============================================================
# FSM PERSISTENCE
# ============================================================

class TestFSMPersistence:
    """FSM state survives save/load."""

    def test_save_and_load_state(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "fsm.json")
        f1 = GoalFSM(memory_path=path)
        f1.set(QuestState.DO_OBJECTIVE, "q_persist")
        f1.total_kills = 5
        f1.total_deaths = 2
        f1.total_xp = 100
        f1.total_copper = 50
        f1.save()

        f2 = GoalFSM(memory_path=path)
        assert f2.state == QuestState.DO_OBJECTIVE
        assert f2.active_quest["id"] == "q_persist"
        assert f2.total_kills == 5
        assert f2.total_deaths == 2
        assert f2.total_xp == 100
        assert f2.total_copper == 50

    def test_save_and_load_giver(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "fsm.json")
        f1 = GoalFSM(memory_path=path)
        f1.set(QuestState.RETURN_TO_GIVER, "q1")
        f1.quest_giver = {"x": 42, "z": 17, "id": "elder"}
        f1.save()

        f2 = GoalFSM(memory_path=path)
        assert f2.quest_giver is not None
        assert f2.quest_giver["x"] == 42
        assert f2.quest_giver["z"] == 17

    def test_load_corrupt_file_resets(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "fsm.json")
        with open(path, "w") as fh:
            fh.write("not json{{{")
        f = GoalFSM(memory_path=path)
        assert f.state == QuestState.QUEST_NONE

    def test_load_unknown_state_resets(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "fsm.json")
        with open(path, "w") as fh:
            import json
            json.dump({"state": "NONEXISTENT_STATE"}, fh)
        f = GoalFSM(memory_path=path)
        assert f.state == QuestState.QUEST_NONE


# ============================================================
# BOUNDED HARNESS
# ============================================================

class TestBoundedHarness:
    """BoundedExecution stops runaway loops."""

    def test_wall_clock_limit(self):
        import time
        b = BoundedExecution(wall_clock_limit=0.01)
        time.sleep(0.02)
        should_stop, reason = b.check(decisions=0)
        assert should_stop
        assert "wall_clock" in reason

    def test_max_decisions_limit(self):
        b = BoundedExecution(max_decisions=5)
        should_stop, reason = b.check(decisions=5)
        assert should_stop
        assert "max_decisions" in reason

    def test_repeated_action_limit(self):
        b = BoundedExecution(max_repeated_action=3)
        for _ in range(3):
            b.record_step(action="explore", is_recovery=False, is_death=False, is_progress=False)
        should_stop, reason = b.check(decisions=0)
        assert should_stop
        assert "max_repeated_action" in reason
        assert "explore" in reason

    def test_dead_streak_limit(self):
        b = BoundedExecution(max_dead_streak=3)
        for _ in range(3):
            b.record_step(action="farm", is_death=True, is_progress=False)
        should_stop, reason = b.check(decisions=0)
        assert should_stop
        assert "max_dead_streak" in reason

    def test_progress_resets_dead_streak(self):
        b = BoundedExecution(max_dead_streak=3)
        b.record_step(action="farm", is_death=True, is_progress=False)
        b.record_step(action="farm", is_death=False, is_progress=True)
        should_stop, reason = b.check(decisions=0)
        assert not should_stop

    def test_recovery_streak_limit(self):
        b = BoundedExecution(max_recovery_streak=3)
        for _ in range(3):
            b.record_step(action="heal", is_recovery=True, is_death=False, is_progress=False)
        should_stop, reason = b.check(decisions=0)
        assert should_stop
        assert "max_recovery_streak" in reason

    def test_non_recovery_resets_recovery_streak(self):
        b = BoundedExecution(max_recovery_streak=3)
        b.record_step(action="heal", is_recovery=True)
        b.record_step(action="farm", is_recovery=False)
        should_stop, reason = b.check(decisions=0)
        assert not should_stop

    def test_summary_reports_state(self):
        b = BoundedExecution()
        b.record_step(action="farm")
        s = b.summary()
        assert s["last_action"] == "farm"
        assert s["repeated_action_count"] == 1
        assert "elapsed_s" in s

    def test_different_action_resets_repeated_count(self):
        b = BoundedExecution(max_repeated_action=3)
        b.record_step(action="farm")
        b.record_step(action="farm")
        b.record_step(action="heal")
        assert b.repeated_action_count == 1
        assert b.last_action == "heal"


# ============================================================
# NAVIGATION INTEGRATION
# ============================================================

class TestNavigationIntegration:
    """Navigation controller + observation work together."""

    def test_nav_to_giver_then_accept(self):
        """Simulate navigating to a giver and reaching it."""
        nav = NavigationController()
        # Giver is 30 yd away
        obs = _obs(ents=[_giver(30, 0)])
        nav.set_target(obs, "quest_giver")
        st = nav.observe(obs)
        assert st["status"] == MOVING

        # Move closer
        obs = _obs(px=20, ents=[_giver(30, 0)])
        st = nav.observe(obs)
        assert st["status"] == MOVING

        # Arrive
        obs = _obs(px=28, ents=[_giver(30, 0)])
        st = nav.observe(obs)
        assert st["status"] == ARRIVED

    def test_stuck_detection(self):
        nav = NavigationController()
        obs = _obs(ents=[_giver(40, 0)])
        nav.set_target(obs, "quest_giver")
        st = None
        for _ in range(10):
            st = nav.observe(obs)  # position never changes
        assert st["status"] == STUCK

    def test_timeout_after_budget(self):
        nav = NavigationController(max_steps_per_target=3)
        obs = _obs(ents=[_giver(100, 0)])
        nav.set_target(obs, "quest_giver")
        st = None
        for i in range(3):
            st = nav.observe(_obs(px=i * 2, ents=[_giver(100, 0)]))
        assert st["status"] == TIMEOUT


# ============================================================
# FSM DECISION INTEGRATION
# ============================================================

class TestFSMDecision:
    """FSM decide() returns correct actions for each state."""

    def test_critical_hp_returns_heal(self):
        f = _fsm()
        f.set(QuestState.DO_OBJECTIVE, "q1")
        action, ctx = f.decide({"hp_frac": 0.1}, {})
        assert action == "heal"
        assert ctx["reason"] == "critical_hp"

    def test_error_with_quest_recovers(self):
        f = _fsm()
        f.set(QuestState.ERROR, "q1")
        action, ctx = f.decide({"quest_status": "ACTIVE"}, {})
        assert f.state == QuestState.DO_OBJECTIVE

    def test_error_without_quest_resets(self):
        f = _fsm()
        f.set(QuestState.ERROR)
        f.active_quest = None
        action, ctx = f.decide({}, {})
        assert f.state == QuestState.QUEST_NONE

    def test_quest_none_with_no_nearby_explores(self):
        f = _fsm()
        action, ctx = f.decide({}, {"nearby": []})
        assert action == "explore"
        assert ctx["reason"] == "no_quest_giver"

    def test_quest_none_with_giver_navigates(self):
        f = _fsm()
        action, ctx = f.decide({}, {"nearby": [_giver(20, 0)]})
        assert f.state == QuestState.FIND_GIVER
        assert action == "navigate"


# ============================================================
# UPDATE_FROM_WORLD EDGE CASES
# ============================================================

class TestUpdateFromWorld:
    """update_from_world syncs FSM with observed quest state."""

    def test_active_from_quest_none(self):
        f = _fsm()
        f.update_from_world({"quest_status": "ACTIVE"})
        assert f.state == QuestState.DO_OBJECTIVE

    def test_ready_from_do_objective(self):
        f = _fsm()
        f.set(QuestState.DO_OBJECTIVE, "q1")
        f.update_from_world({"quest_status": "READY_TO_TURN_IN"})
        assert f.state == QuestState.RETURN_TO_GIVER

    def test_done_from_verify_turn_in(self):
        f = _fsm()
        f.set(QuestState.VERIFY_TURN_IN, "q1")
        f.update_from_world({"quest_status": "DONE"})
        assert f.state == QuestState.DONE

    def test_none_from_done_resets(self):
        f = _fsm()
        f.set(QuestState.DONE, "q1")
        f.update_from_world({"quest_status": "NONE"})
        assert f.state == QuestState.QUEST_NONE
        assert f.active_quest is None

    def test_turnin_demotes_when_active(self):
        """Fix5 regression: TURN_IN against incomplete ACTIVE demotes."""
        f = _fsm()
        f.set(QuestState.TURN_IN, "q_greyjaw")
        f.update_from_world({"quest_status": "ACTIVE"})
        assert f.state == QuestState.DO_OBJECTIVE

    def test_verify_turnin_demotes_when_active(self):
        f = _fsm()
        f.set(QuestState.VERIFY_TURN_IN, "q1")
        f.update_from_world({"quest_status": "ACTIVE"})
        assert f.state == QuestState.DO_OBJECTIVE


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
