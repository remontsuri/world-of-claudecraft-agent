import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _info(corpses=0, nodes=0, hp=142):
    nearby = []
    for i in range(corpses):
        nearby.append({"id": 100 + i, "kind": "mob", "dead": True, "lootable": True,
                       "componentTags": ["silk"], "dist": 5.0,
                       "x": 1.0, "z": 1.0, "name": "spider"})
    gather = {"nearbyNodes": [{"id": 200 + i, "harvestable": True, "dist": 6.0}
                             for i in range(nodes)]}
    return {
        "player": {"hp": hp, "maxHp": 142, "dead": False},
        "player_pos": [0, 0],
        "nearby": nearby,
        "gather": gather,
        "inventory": [{"itemId": "spider_silk", "count": 5}],
        "quests": {
            "active": [{"id": "q_prof_workorder_loom", "state": "active",
                        "objectives": [{"current": 5, "required": 6}],
                        "turnInNpc": None}],
            "ready": [], "done": [],
        },
    }


def _gm(step_idx=1):
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    gm.step_idx = step_idx
    return gm


def test_gather_filtered_out_when_no_object_nearby():
    """Q5 (гибрид, согласовано с со-архитектором): без узла и без трупа рядом
    gather НЕ должен предлагаться — измерено 25/171 = 14.6% шагов уходило в
    пустые вызовы."""
    gm = _gm(step_idx=1)
    info = _info(corpses=0, nodes=0)
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "gather" not in cands, f"gather предложен без объекта: {cands}"


def test_gather_offered_when_corpse_nearby():
    """Труп с componentTags рядом — законный объект для harvestCorpse."""
    gm = _gm(step_idx=1)
    info = _info(corpses=1, nodes=0)
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "gather" in cands, f"gather не предложен при трупе рядом: {cands}"


def test_gather_offered_when_node_nearby():
    gm = _gm(step_idx=1)
    info = _info(corpses=0, nodes=1)
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "gather" in cands, f"gather не предложен при узле рядом: {cands}"


def test_exploration_budget_allows_periodic_probe():
    """Разведочный бюджет: раз в GATHER_PROBE_EVERY шагов пробуем вопреки
    фильтру — мир мог измениться незаметно для снапшота."""
    from policy import GATHER_PROBE_EVERY
    gm = _gm(step_idx=GATHER_PROBE_EVERY)
    info = _info(corpses=0, nodes=0)
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "gather" in cands, (
        f"разведочная проба не сработала на шаге {GATHER_PROBE_EVERY}: {cands}")


def test_probe_is_rare_not_every_step():
    from policy import GATHER_PROBE_EVERY
    gm = _gm(step_idx=GATHER_PROBE_EVERY + 1)
    info = _info(corpses=0, nodes=0)
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "gather" not in cands, "проба должна быть редкой, не каждый шаг"
