"""test_gather_bag_cycle.py — цикл «полные сумки -> продать -> вернуться к добыче».

Корень (2026-08-25): сумки 26/26 блокируют harvestNode (bagsFullError,
gathering.ts capacity pre-gate), а фаза DO_OBJECTIVE не допускает
SKILL_SELL (PHASE_ALLOWED) -> агент бесконечно inconclusive у узла.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _info_full_bags():
    """Живой мир: сумки полны, рядом нет вендора."""
    inv = [{"itemId": f"junk_{i}", "count": 5, "quality": 0} for i in range(24)]
    inv.append({"itemId": "copper_mining_pick", "count": 1, "quality": 0})
    inv.append({"itemId": "rough_hide", "count": 20, "quality": 0})
    return {
        "player": {"hp": 164, "maxHp": 164, "dead": False},
        "mana": 700, "maxMana": 700, "abilities": [],
        "player_pos": [-62.0, -68.0],
        "nearby": [],  # вендора рядом нет
        "inventory": inv,
        "bagCapacity": 26,
        "quests": {"active": [
            {"id": "q_prof_workorder_forge", "state": "active",
             "objectives": [{"type": "collect", "itemId": "copper_ore",
                             "current": 0, "required": 8}]},
        ], "ready": [], "done": []},
        "recipes_known": [], "stations": [],
        "kills": 900, "xp": 2000, "copper": 500, "deaths": 800,
        "in_combat": False,
    }


def test_sell_allowed_in_do_objective_phase():
    """SKILL_SELL должен быть в PHASE_ALLOWED['DO_OBJECTIVE']."""
    from policy import PHASE_ALLOWED, SKILL_SELL
    assert SKILL_SELL in PHASE_ALLOWED["DO_OBJECTIVE"], \
        "полные сумки в поле — без sell агент никогда не разгрузится"


def test_full_bags_force_sell_even_without_nearby_vendor():
    """При ПОЛНЫХ сумках политика выбирает sell, даже если вендора нет рядом
    (мост/skill сам дойдёт до запомненного вендора)."""
    from policy import GoalManager, SKILL_SELL
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    info = _info_full_bags()
    ws = gm._world_state(info)
    action, ctx = gm.decide(info, ws=ws, goal="DO_OBJECTIVE")
    assert action == SKILL_SELL, (
        f"сумки полны ({ws.get('inv_slots')}/{ws.get('bag_capacity')}): "
        f"ожидал sell_junk, получили {action}")


def test_sell_ctx_carries_keepids_for_quest_materials(tmp_path=None):
    """При продаже copper_ore/ironbark_log (квестовые) защищены keepIds."""
    from policy import GoalManager, SKILL_SELL
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    info = _info_full_bags()
    ws = gm._world_state(info)
    action, ctx = gm.decide(info, ws=ws, goal="DO_OBJECTIVE")
    if action == SKILL_SELL:
        # квестовый collect-предмет не должен попасть под продажу
        assert "copper_ore" in (ctx.get("keepIds") or []), \
            "copper_ore нужен для q_prof_workorder_forge — он в keepIds"
