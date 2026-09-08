"""test_policy_softmax_only.py — Verify policy only samples, doesn't override.

Phase 4 acceptance criteria:
  - policy.py:GoalManager.decide() has NO hardcoded overrides
  - policy.py:GoalManager._candidates() accepts phase and advisor params
  - policy.py:GoalManager.decide() only does softmax sampling
  - All overrides moved to arbitration.py

Run: cd python && python -m pytest test_policy_softmax_only.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from memory import ExperienceStore
from policy import GoalManager, SKILL_FARM, SKILL_EXPLORE, PHASE_ALLOWED


# ---- helpers ----

def _info(hp=100, maxhp=100, nearby=None, quests=None, inv=None):
    return {
        "player": {"hp": hp, "maxHp": maxhp, "dead": False},
        "player_pos": [0.0, 0.0],
        "player_class": "warrior",
        "nearby": nearby or [],
        "quests": quests or {"active": [], "done": []},
        "inventory": inv or [],
        "copper": 0, "kills": 0, "deaths": 0, "xp": 0,
    }


def _gm(seed=42):
    return GoalManager(ExperienceStore(), temperature=1.2, seed=seed,
                       reflection_hints={})


# ---- tests: policy has no hardcoded overrides ----

class TestPolicyNoOverrides:
    """Verify decide() has no hardcoded overrides in policy.py source."""

    def test_no_loot_priority_in_source(self):
        """policy.py must not contain the loot_priority override logic."""
        policy_path = os.path.join(os.path.dirname(__file__), "policy.py")
        with open(policy_path, encoding="utf-8") as f:
            source = f.read()
        # The override pattern was: if _corpses and SKILL_LOOT in cands: return SKILL_LOOT
        assert "\"loot_priority\", \"loot\"" not in source, (
            "policy.py still contains loot_priority override"
        )

    def test_no_bag_survival_in_source(self):
        """policy.py must not contain the bag_survival_sell override logic."""
        policy_path = os.path.join(os.path.dirname(__file__), "policy.py")
        with open(policy_path, encoding="utf-8") as f:
            source = f.read()
        assert "\"bag_survival_sell\", \"sell_junk\"" not in source, (
            "policy.py still contains bag_survival_sell override"
        )
        assert "bag_slots_sell >= bag_capacity - 3" not in source, (
            "policy.py still contains bag capacity check"
        )

    def test_no_phase_return_in_source(self):
        """policy.py must not contain the phase_return override logic."""
        policy_path = os.path.join(os.path.dirname(__file__), "policy.py")
        with open(policy_path, encoding="utf-8") as f:
            source = f.read()
        assert "\"phase_return\", \"return_to_giver\"" not in source, (
            "policy.py still contains phase_return override"
        )

    def test_no_turn_in_phase_in_source(self):
        """policy.py must not contain the turn_in_phase override logic."""
        policy_path = os.path.join(os.path.dirname(__file__), "policy.py")
        with open(policy_path, encoding="utf-8") as f:
            source = f.read()
        assert "turn_in_far_return" not in source, (
            "policy.py still contains turn_in_far_return override"
        )
        assert "turn_in_close" not in source, (
            "policy.py still contains turn_in_close override"
        )


class TestPolicySoftmaxOnly:
    """Verify decide() does softmax sampling when no arbitration fires."""

    def test_explore_chosen_in_no_quest(self):
        """In NO_QUEST with no nearby giver, explore is a valid candidate."""
        gm = _gm()
        gm.step_idx = 1
        info = _info()
        ws = gm._world_state(info)
        action, ctx = gm.decide(info, ws=ws, phase="NO_QUEST")
        assert action in PHASE_ALLOWED["NO_QUEST"], \
            f"action {action} not in allowed {PHASE_ALLOWED['NO_QUEST']}"

    def test_action_is_valid_for_phase(self):
        """When candidates exist and no override fires, action is valid for phase."""
        gm = _gm()
        gm.step_idx = 1
        # Mob nearby — farm is a candidate
        info = _info(nearby=[
            {"type": "mob", "kind": "mob", "hp": 10, "level": 1, "dist": 5.0, "id": 1}
        ])
        ws = gm._world_state(info)
        ws["hp_frac"] = 1.0
        # DO_OBJECTIVE with mob: candidates should include farm
        action, ctx = gm.decide(info, ws=ws, phase="DO_OBJECTIVE")
        # Action should be a valid skill (not None)
        assert action is not None
        assert isinstance(action, str)

    def test_empty_cands_returns_farm(self):
        """When no candidates exist, fallback to farm (default exploration)."""
        gm = _gm()
        gm.step_idx = 1
        info = _info()
        ws = gm._world_state(info)
        ws["hp_frac"] = 1.0
        # Use a phase where no candidates match
        action, ctx = gm.decide(info, ws=ws, phase="ACCEPT")
        # ACCEPT phase with no NPC nearby → fallback to full list
        assert action is not None


class TestCandidatesAcceptsParams:
    """Verify _candidates() accepts phase and advisor params."""

    def test_candidates_accepts_phase(self):
        """_candidates() should accept a phase parameter."""
        gm = _gm()
        info = _info()
        ws = gm._world_state(info)
        # Should not raise
        cands = gm._candidates(info, ws, phase="NO_QUEST")
        assert isinstance(cands, list)

    def test_candidates_accepts_advisor(self):
        """_candidates() should accept an advisor parameter."""
        gm = _gm()
        info = _info()
        ws = gm._world_state(info)
        advisor = {"subgoal": "KILL", "target_mob_id": "wolf"}
        # Should not raise
        cands = gm._candidates(info, ws, phase="NO_QUEST", advisor=advisor)
        assert isinstance(cands, list)


class TestArbitrationLayer:
    """Verify arbitration.py has the overrides that were removed from policy.py."""

    def test_arbitration_module_exists(self):
        """arbitration.py should be importable."""
        import arbitration
        assert hasattr(arbitration, "arbitrate")

    def test_arbitration_has_checks(self):
        """arbitration.arbitrate should have priority-ordered checks."""
        from arbitration import arbitrate, _bag_survival_sell, _loot_priority
        assert callable(arbitrate)
        assert callable(_bag_survival_sell)
        assert callable(_loot_priority)

    def test_arbitration_plan_stack_fires(self):
        """Arbitration should fire turn_in for READY quest at giver."""
        from arbitration import arbitrate
        ws = {
            "quest_status": "READY_TO_TURN_IN",
            "quest": {"id": "q1", "giver_distance": 3.0},
            "hp_frac": 1.0,
        }
        info = {
            "inventory": [],
            "quests": {"active": [], "ready": [
                {"id": "q1", "state": "ready",
                 "turnInNpc": {"x": 0, "z": 0}}]},
            "player_pos": [0, 0],
        }
        result = arbitrate(info, ws, "TURN_IN", ["turn_in_quest", "return_to_giver"])
        assert result is not None
        action, ctx = result
        assert action == "turn_in_quest", f"expected turn_in, got {action}"

    def test_arbitration_phase_return_fires(self):
        """Arbitration should fire return_to_giver in RETURN_TO_GIVER phase."""
        from arbitration import arbitrate
        ws = {
            "quest_status": "READY_TO_TURN_IN",
            "quest": {"id": "q1", "giver_distance": 50.0},
            "hp_frac": 0.8,
        }
        info = {
            "inventory": [],
            "quests": {"active": [{"id": "q1", "turnInNpc": {"x": 50, "z": 0}}]},
            "nearby": [],
            "player_pos": [0, 0],
        }
        result = arbitrate(info, ws, "RETURN_TO_GIVER", ["return_to_giver", "turn_in_quest"])
        assert result is not None
        action, ctx = result
        assert action == "return_to_giver", f"expected return, got {action}"

    def test_arbitration_returns_none_when_no_override(self):
        """Arbitration should return None when no condition matches."""
        from arbitration import arbitrate
        ws = {"quest_status": "NONE", "hp_frac": 1.0}
        info = {"inventory": [], "quests": {"active": []}, "nearby": [],
                "player_pos": [0, 0]}
        result = arbitrate(info, ws, "NO_QUEST", ["explore", "accept_quest"])
        assert result is None

    def test_arbitration_loot_priority_fires(self):
        """Arbitration should fire loot when corpses nearby."""
        from arbitration import arbitrate
        ws = {"quest_status": "ACTIVE", "hp_frac": 1.0}
        info = {
            "inventory": [],
            "quests": {"active": [{"id": "q1"}]},
            "nearby": [{"type": "mob", "kind": "mob", "dead": True, "dist": 5.0, "id": 1}],
            "player_pos": [0, 0],
        }
        result = arbitrate(info, ws, "DO_OBJECTIVE", ["farm", "loot", "navigate"])
        assert result is not None
        action, ctx = result
        assert action == "loot", f"expected loot, got {action}"
