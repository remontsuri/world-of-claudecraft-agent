"""test_plan_stack.py — Plan-Stack: квест становится транзакцией с планом.

Фарм-бот диагноз (2026-08-25): агент собирал copper_ore 5/8 и продолжал
фармить волков, не зная что 3 ore = поход к Darva + turn_in. Причина:
квест — фон, а не план. Политика выбирает действие заново каждый шаг.

Контракт Plan-Stack:
  1. У квеста с incomplete objective -> план [GATHER/FARM objective]
  2. Все objectives полные (или state=ready) -> план [RETURN_TO_GIVER, TURN_IN]
     и политика ОБЯЗАНА вернуть return_to_giver, а не farm
  3. План живёт в FSM: шаг выполняется до завершения, не пересэмплируется
  4. Сдача -> план пуст -> обычная политика (следующий квест)
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _info(ore=5, ready=False):
    """Живая схема снапшота (проверена schema contract test)."""
    objs = [{"type": "collect", "itemId": "copper_ore", "current": ore,
             "required": 8}] if not ready else []
    q = {"id": "q_prof_workorder_forge", "state": "ready" if ready else "active",
         "objectives": objs,
         "turnInNpc": {"x": -34.4, "z": -36.2}}  # forgemistress_darva
    return {
        "player": {"hp": 186, "maxHp": 186, "dead": False},
        "mana": 700, "maxMana": 700,
        "player_pos": [-11.4, 11.4], "nearby": [],
        "inventory": [{"itemId": "copper_mining_pick", "count": 1},
                      {"itemId": "copper_ore", "count": ore}],
        "bagCapacity": 26,
        "quests": {"active": [] if ready else [q], "ready": [q] if ready else [], "done": []},
        "recipes_known": [], "stations": [],
        "kills": 1000, "xp": 5000, "copper": 500, "deaths": 900,
        "in_combat": False,
    }


def _gm():
    from policy import GoalManager
    from memory import ExperienceStore
    return GoalManager(ExperienceStore(), reflection_hints={})


def test_incomplete_objective_plan_is_gather():
    """Квест 5/8 -> политика ведёт к добыче (gather/farm), не sell."""
    gm = _gm()
    info = _info(ore=5)
    ws = gm._world_state(info)
    action, ctx = gm.decide(info, ws=ws, goal="DO_OBJECTIVE")
    assert action in ("gather", "farm"), \
        f"5/8 ore: ожидал gather/farm, получили {action}"


def test_complete_objective_forces_return_to_giver():
    """ГЛАВНЫЙ тест фарм-бот фикса: 8/8 -> ОБЯЗАН идти сдавать, не farm.
    Гивер далеко (52 yd) -> return_to_giver (шаг стека 'дойти')."""
    gm = _gm()
    info = _info(ore=8)
    info["quests"]["active"] = [{
        "id": "q_prof_workorder_forge", "state": "active",
        "objectives": [{"type": "collect", "itemId": "copper_ore",
                        "current": 8, "required": 8}],
        "turnInNpc": {"x": -34.4, "z": -36.2},
    }]
    ws = gm._world_state(info)
    assert ws["quest"].get("complete") is True or ws["quest"].get("phase") == "READY", \
        f"world_state должен видеть завершённый квест: {ws.get('quest')}"
    action, ctx = gm.decide(info, ws=ws, goal="DO_OBJECTIVE")
    assert action in ("return_to_giver", "turn_in_quest"), \
        f"8/8 ore: агент обязан идти сдавать, получили {action} — это и есть фарм-бот"
    assert action != "farm" and action != "gather", \
        f"8/8: продолжать фармить = фарм-бот. Получили {action}"


def test_ready_quest_at_giver_forces_turn_in():
    """READY-квест У ГИВЕРА (dist<=6) -> сразу turn_in_quest (следующий шаг стека)."""
    gm = _gm()
    info = _info(ready=True)
    info["player_pos"] = [-34.0, -36.0]  # стоим у гивера
    info["nearby"] = [{"kind": "npc", "id": 12, "name": "Forgemistress Darva",
                       "x": -34.4, "z": -36.2, "dist": 3.0}]
    ws = gm._world_state(info)
    assert ws["quest"].get("phase") == "READY", f"{ws['quest']}"
    assert ws["quest"].get("giver_distance", 999) <= 6, \
        f"тест предполагает гивера рядом, dist={ws['quest'].get('giver_distance')}"
    action, ctx = gm.decide(info, ws=ws, goal="TURN_IN")
    assert action == "turn_in_quest", f"READY у гивера: ожидал turn_in, получили {action}"
    assert ctx.get("questId"), "turn_in без questId — верификатор ослепнёт"
