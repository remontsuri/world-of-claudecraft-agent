"""FIX #1 regression: quest_available uses questState, not just bool(givers).

Iron invariant (2026-08-27):
  qs=NONE + 11 givers + 0 available quests → accept_quest attempts = 0

Before fix: quest_available = bool(givers) → True when NPC has questIds
            even if questState == 'done'/'active'/'unavailable'
After fix:  quest_available = exists giver AND questState == 'available'
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from observation import encode_observation
from skill_contracts import check_preconditions


def _make_ws(quest_states=None, giver_count=0, giver_quest_ids=None):
    """Build a minimal world state for encode_observation."""
    if quest_states is None:
        quest_states = {}
    if giver_quest_ids is None:
        giver_quest_ids = []

    nearby = []
    for i in range(giver_count):
        nearby.append({
            "kind": "npc",
            "name": f"NPC_{i}",
            "id": 1000 + i,
            "templateId": f"npc_{i}",
            "x": 5.0 + i, "z": 0.0,
            "dist": 5.0 + i,
            "questIds": giver_quest_ids,
        })

    return {
        "player": {"hp": 100, "maxHp": 100, "level": 5, "dead": False},
        "player_pos": [0.0, 0.0],
        "player_class": "warrior",
        "nearby": nearby,
        "quests": {"active": [], "ready": [], "done": []},
        "inventory": [], "inventory_by_id": {}, "equipment": {},
        "copper": 50, "kills": 0, "deaths": 0, "xp": 0,
        "bagCapacity": 16,
        "quest_states": quest_states,
        "hp_frac": 1.0,
        "bag_capacity": 16,
    }


# --- Test 1: givers present but quest_state=done → quest_available=False ---
def test_givers_with_done_quest_not_available():
    ws = _make_ws(
        quest_states={"q_wolves": "done"},
        giver_count=1,
        giver_quest_ids=["q_wolves"],
    )
    obs = encode_observation(ws, {})
    assert obs["world"]["quest_available"] is False, (
        "quest_available должно быть False когда questState='done', "
        f"получено: {obs['world']['quest_available']}"
    )


# --- Test 2: givers present, quest_state=available → quest_available=True ---
def test_givers_with_available_quest():
    ws = _make_ws(
        quest_states={"q_boars": "available"},
        giver_count=1,
        giver_quest_ids=["q_boars"],
    )
    obs = encode_observation(ws, {})
    assert obs["world"]["quest_available"] is True, (
        "quest_available должно быть True когда questState='available', "
        f"получено: {obs['world']['quest_available']}"
    )


# --- Test 3: no givers → quest_available=False regardless of quest_states ---
def test_no_givers_quest_unavailable():
    ws = _make_ws(
        quest_states={"q_boars": "available"},
        giver_count=0,
    )
    obs = encode_observation(ws, {})
    assert obs["world"]["quest_available"] is False


# --- Test 4: IRON INVARIANT: 11 givers, 0 available quests → quest_available=False ---
def test_iron_invariant_no_available():
    """Железный invariant: 11 NPC с questIds но ни один quest не available.

    Симулирует V0 баг: NPC имеют questIds (done/active/unavailable),
    но accept_quest не должен вызываться.
    """
    quest_states = {
        "q_wolves": "done",
        "q_bandits": "active",
        "q_supplies": "unavailable",
        "q_spiders": "done",
        "q_murlocs": "done",
        "q_bones": "done",
        "q_whispers": "done",
    }
    giver_quest_ids = list(quest_states.keys())

    ws = _make_ws(
        quest_states=quest_states,
        giver_count=11,
        giver_quest_ids=giver_quest_ids,
    )
    obs = encode_observation(ws, {})
    assert obs["world"]["quest_available"] is False, (
        f"Железный invariant нарушен: 11 givers без available quest, "
        f"но quest_available={obs['world']['quest_available']}"
    )
    # И проверяем что accept_quest заблокирован
    result = check_preconditions("accept_quest", obs)
    assert result["ok"] is False
    assert "quest_available" in result["failed"]


# --- Test 5: mixed: some done, one available → quest_available=True ---
def test_mixed_one_available():
    quest_states = {
        "q_wolves": "done",
        "q_bandits": "active",
        "q_boars": "available",
        "q_supplies": "unavailable",
    }
    giver_quest_ids = list(quest_states.keys())

    ws = _make_ws(
        quest_states=quest_states,
        giver_count=4,
        giver_quest_ids=giver_quest_ids,
    )
    obs = encode_observation(ws, {})
    assert obs["world"]["quest_available"] is True


# --- Test 6: quest_states empty/missing → fail-closed to False ---
def test_no_quest_states_field():
    """quest_states отсутствует → fail-closed (False), не паника."""
    ws = _make_ws(
        quest_states=None,
        giver_count=1,
        giver_quest_ids=["q_boars"],
    )
    ws.pop("quest_states", None)
    obs = encode_observation(ws, {})
    # Без quest_states не можем подтвердить availability → False
    assert obs["world"]["quest_available"] is False


# --- Test 7: multiple givers, each with different quests ---
def test_multiple_givers_different_quests():
    """3 NPC разные квесты, только один available."""
    ws = _make_ws(
        quest_states={
            "q_wolves": "done",
            "q_boars": "available",
            "q_supplies": "unavailable",
        },
        giver_count=3,
        giver_quest_ids=[["q_wolves"], ["q_boars"], ["q_supplies"]],
    )
    # Build properly with per-giver quest lists
    ws["nearby"] = [
        {"kind": "npc", "name": "A", "id": 1, "templateId": "a",
         "x": 3, "z": 0, "dist": 3, "questIds": ["q_wolves"]},
        {"kind": "npc", "name": "B", "id": 2, "templateId": "b",
         "x": 5, "z": 0, "dist": 5, "questIds": ["q_boars"]},
        {"kind": "npc", "name": "C", "id": 3, "templateId": "c",
         "x": 7, "z": 0, "dist": 7, "questIds": ["q_supplies"]},
    ]
    obs = encode_observation(ws, {})
    assert obs["world"]["quest_available"] is True


if __name__ == "__main__":
    test_givers_with_done_quest_not_available()
    test_givers_with_available_quest()
    test_no_givers_quest_unavailable()
    test_iron_invariant_no_available()
    test_mixed_one_available()
    test_no_quest_states_field()
    test_multiple_givers_different_quests()
    print("ALL 7 FIX #1 TESTS PASSED")
