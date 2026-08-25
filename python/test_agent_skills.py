"""test_agent_skills.py — полный набор скиллов агента для экономики игры."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def test_policy_has_gather_skills():
    """Политика имеет buy/equip и формирует покупку инструмента для gather-квестов."""
    from policy import SKILL_BUY, SKILL_EQUIP, GoalManager
    from memory import ExperienceStore
    assert SKILL_BUY == "buy"
    assert SKILL_EQUIP == "equip"

    # q_toolworks требует ironbark_log (wood → logging_axe)
    info = {
        "player": {"hp": 164, "maxHp": 164, "dead": False},
        "mana": 700, "maxMana": 700, "abilities": [],
        "player_pos": [0, 0], "nearby": [],
        "inventory": [{"itemId": "copper_mining_pick", "count": 1}],
        "bagCapacity": 26,
        "quests": {"active": [
            {"id": "q_toolworks", "state": "active",
             "objectives": [{"type": "gather", "nodeType": "wood",
                             "current": 0, "required": 8}]},
        ], "ready": [], "done": []},
        "recipes_known": [], "stations": [],
        "kills": 900, "xp": 2000, "copper": 500, "deaths": 800,
        "in_combat": False,
    }
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    ws = gm._world_state(info)
    assert ws.get("needs_tool") == "logging_axe", \
        f"для wood нужен logging_axe, получили: {ws.get('needs_tool')}"


def test_buy_forces_when_tool_missing():
    """Если нужен инструмент для gather и его нет → форсируем buy."""
    from policy import GoalManager, SKILL_BUY
    from memory import ExperienceStore
    info = {
        "player": {"hp": 164, "maxHp": 164, "dead": False},
        "mana": 700, "maxMana": 700, "abilities": [],
        "player_pos": [0, 0], "nearby": [],
        "inventory": [{"itemId": "copper_mining_pick", "count": 1}],
        "bagCapacity": 26,
        "quests": {"active": [
            {"id": "q_toolworks", "state": "active",
             "objectives": [{"type": "gather", "nodeType": "wood",
                             "current": 0, "required": 8}]},
        ], "ready": [], "done": []},
        "recipes_known": [], "stations": [],
        "kills": 900, "xp": 2000, "copper": 500, "deaths": 800,
        "in_combat": False,
    }
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    ws = gm._world_state(info)
    action, ctx = gm.decide(info, ws=ws, goal="DO_OBJECTIVE")
    assert action == SKILL_BUY, \
        f"нет logging_axe для wood квеста → ожидал buy, получили {action}"
    assert ctx.get("buyItemId") == "logging_axe", \
        f"должны покупать logging_axe, получили: {ctx.get('buyItemId')}"
