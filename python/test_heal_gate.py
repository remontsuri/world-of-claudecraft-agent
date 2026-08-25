"""test_heal_gate.py — heal не предлагается при полном HP.

Замер (прогон 2026-08-25): heal_rejected x16 — агент тратил шаги на heal
при hp_frac=1.0, сервер отклонял каст. Причина: hp_frac < 1.0 срабатывает
на 163/164 HP (один урон от моба), а cast уже отклоняется игрой при
hp==maxHp после регена. Gate: heal предлагается только при реальном
дефиците HP.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _info(hp):
    return {
        "player": {"hp": hp, "maxHp": 164, "dead": False},
        "mana": 700, "maxMana": 700,
        "player_pos": [0, 0], "nearby": [],
        "inventory": [{"itemId": "minor_healing_potion", "count": 2}],
        "bagCapacity": 26,
        "quests": {"active": [], "ready": [], "done": []},
        "recipes_known": [], "stations": [],
        "kills": 1, "xp": 10, "copper": 100, "deaths": 0,
        "in_combat": False,
    }


def test_no_heal_at_full_hp():
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    info = _info(164)
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "heal" not in cands, f"полный HP — heal не нужен: {cands}"
