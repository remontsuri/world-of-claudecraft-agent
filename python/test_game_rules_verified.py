import os, sys
sys.path.insert(0, os.path.dirname(__file__))


# ---------- C1: две РАЗНЫЕ дистанции, а не одна ----------

def test_quest_range_is_interact_plus_two():
    """Проверено по исходникам игры (субагент + я):
    src/sim/types.ts:26          -> INTERACT_RANGE = 5
    quests/quest_commands.ts:148 -> dist <= INTERACT_RANGE + 2  (квесты = 7)
    interaction.ts:304           -> dist > INTERACT_RANGE       (харвест = 5)
    Раньше я захардкодил 7.0 под именем INTERACT_RANGE — угадал число для
    квестов, но для харвеста/лута это НЕВЕРНО."""
    from quest_truth import INTERACT_RANGE, QUEST_INTERACT_RANGE, HARVEST_RANGE
    assert INTERACT_RANGE == 5.0, "константа игры types.ts:26"
    assert QUEST_INTERACT_RANGE == 7.0, "квест-гейт = INTERACT_RANGE + 2"
    assert HARVEST_RANGE == 5.0, "харвест использует сырую INTERACT_RANGE"


def test_turn_in_allowed_within_seven_not_five():
    from quest_truth import QuestTruth
    snap = {"player_pos": [0.0, 0.0], "nearby": [],
            "quests": {"active": [], "done": [],
                       "ready": [{"id": "q_a", "state": "ready",
                                  "objectives": [{"current": 1, "required": 1}],
                                  "turnInNpc": {"x": 6.0, "z": 0.0}}]}}
    assert QuestTruth(snap).can_turn_in("q_a") is True, "6yd < 7yd — сдача возможна"
    snap["quests"]["ready"][0]["turnInNpc"] = {"x": 8.0, "z": 0.0}
    assert QuestTruth(snap).can_turn_in("q_a") is False, "8yd > 7yd — сервер откажет"


# ---------- C3: гейт identity-transition (найден мной, подтверждён) ----------

def test_identity_transition_quest_blocked_when_one_active():
    """quest_commands.ts:104-109: пока в логе ЛЮБОЙ attunePair/switchHobby квест,
    все остальные такие квесты unavailable. Живая проверка: у агента активен
    q_prof_attune_smith, поэтому 9 квестов вокруг физически недоступны, и все
    7 accept_quest дали inconclusive."""
    from quest_truth import is_identity_transition, accept_blocked_by_identity
    assert is_identity_transition("q_prof_attune_outfitter") is True
    assert is_identity_transition("q_prof_amends_smith") is True
    assert is_identity_transition("q_prof_hobby_switch") is True
    assert is_identity_transition("q_bones") is False
    assert is_identity_transition("q_prof_workorder_loom") is False, "work-order — не identity"

    active = ["q_prof_attune_smith", "q_greyjaw"]
    assert accept_blocked_by_identity("q_prof_attune_outfitter", active) is True
    assert accept_blocked_by_identity("q_bones", active) is False
    assert accept_blocked_by_identity("q_prof_attune_outfitter", ["q_greyjaw"]) is False


def test_accept_candidate_filters_identity_blocked():
    """Политика не должна предлагать accept для заблокированного квеста."""
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    gm.step_idx = 1
    info = {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [0.0, 0.0],
        "inventory": [],
        "nearby": [{"id": 1, "kind": "npc", "name": "Weaver", "dist": 5.0,
                    "x": 3.0, "z": 3.0,
                    "questIds": ["q_prof_attune_outfitter", "q_prof_amends_outfitter"]}],
        "quests": {"active": [{"id": "q_prof_attune_smith", "state": "active",
                               "objectives": [{"current": 0, "required": 3}]}],
                   "ready": [], "done": []},
    }
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "accept_quest" not in cands, (
        f"предложен accept для identity-заблокированных квестов: {cands}")


def test_accept_offered_for_normal_quest_nearby():
    """А обычный квест (q_bones у Brother Aldric) брать можно."""
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    gm.step_idx = 1
    info = {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [0.0, 0.0],
        "inventory": [],
        "nearby": [{"id": 2, "kind": "npc", "name": "Aldric", "dist": 5.0,
                    "x": 3.0, "z": 3.0, "questIds": ["q_bones", "q_whispers"]}],
        "quests": {"active": [{"id": "q_prof_attune_smith", "state": "active",
                               "objectives": [{"current": 0, "required": 3}]}],
                   "ready": [], "done": []},
        # FIX #1 (2026-08-27): quest_states для квестов NPC
        "quest_states": {"q_bones": "available", "q_whispers": "available"},
    }
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "accept_quest" in cands, f"обычный квест должен предлагаться: {cands}"


# ---------- КОРЕНЬ: далеко от гивера -> идти, а не пытаться сдать ----------

def test_turn_in_phase_far_from_giver_walks_instead_of_turning_in():
    """ГЛАВНАЯ находка верификатора: гиверы были в 59-65 yd при гейте 7 yd.
    Агент 67 шагов стоял в фазе TURN_IN и 7 раз вызывал turn_in_quest
    (все INCONCLUSIVE), а return_to_giver — НИ РАЗУ. Никакая правка констант
    это не лечит: нужно ИДТИ к гиверу."""
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    gm.step_idx = 1
    info = {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [0.0, 0.0],
        "inventory": [],
        "nearby": [],
        "quests": {"active": [], "done": [],
                   "ready": [{"id": "q_loom", "state": "ready",
                              "objectives": [{"current": 6, "required": 6}],
                              "turnInNpc": {"x": 60.0, "z": 0.0}}]},
    }
    ws = gm._world_state(info)
    action, ctx = gm.decide(info, ws=ws, goal="TURN_IN")
    assert action == "return_to_giver", (
        f"при 60yd до гивера надо ИДТИ, а не сдавать; выбрано: {action}")


def test_turn_in_phase_close_to_giver_turns_in():
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    gm.step_idx = 1
    info = {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [0.0, 0.0],
        "inventory": [],
        "nearby": [],
        "quests": {"active": [], "done": [],
                   "ready": [{"id": "q_loom", "state": "ready",
                              "objectives": [{"current": 6, "required": 6}],
                              "turnInNpc": {"x": 4.0, "z": 0.0}}]},
    }
    ws = gm._world_state(info)
    action, ctx = gm.decide(info, ws=ws, goal="TURN_IN")
    assert action == "turn_in_quest", f"в 4yd надо сдавать; выбрано: {action}"
