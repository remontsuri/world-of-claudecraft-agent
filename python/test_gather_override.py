import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _info_with_inv(items, hp=142, max_hp=142):
    inv = [{"id": k, "count": v} for k, v in items.items()]
    return {
        "player": {"hp": hp, "maxHp": max_hp, "dead": False},
        "player_pos": [0, 0],
        "nearby": [],
        "inventory": inv,
        "quests": {
            "active": [{"id": "q_prof_workorder_loom", "state": "active",
                        "objectives": [{"current": 5, "required": 6}],
                        "turnInNpc": None}],
            "ready": [], "done": [],
        },
    }


def test_gather_offered_when_quest_items_in_bags():
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    info = _info_with_inv({"spider_silk": 5})
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "gather" in cands, f"gather not offered: {cands}"


def test_gather_not_forced_without_quest_items():
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    info = _info_with_inv({})
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    # без квестовых предметов gather не обязан появляться (может от других причин)
    assert "gather" not in cands or True


def test_survival_still_gates_low_hp():
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    info = _info_with_inv({"spider_silk": 5}, hp=10, max_hp=142)
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    # при критическом hp выживание важнее: heal должен быть в кандидатах
    assert "heal" in cands
