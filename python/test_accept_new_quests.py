import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _info(npc_quests=(), have=(), dist=8.0, hp=100):
    """npc_quests: список questIds у NPC рядом; have: наши уже взятые квесты."""
    nearby = []
    if npc_quests:
        nearby.append({"id": 900, "kind": "npc", "name": "Giver",
                       "dist": dist, "x": 5.0, "z": 5.0,
                       "questIds": list(npc_quests)})
    # FIX #1 (2026-08-27): quest_states для квестов NPC.
    # Если квест не в логе (have) — считаем его "available" для тестов.
    quest_states = {}
    for qid in npc_quests:
        if qid not in have:
            quest_states[qid] = "available"
    return {
        "player": {"hp": hp, "maxHp": 100, "dead": False},
        "player_pos": [0.0, 0.0],
        "nearby": nearby,
        "inventory": [],
        "quest_states": quest_states,
        "quests": {
            "active": [{"id": q, "state": "active",
                        "objectives": [{"current": 1, "required": 5}],
                        "turnInNpc": {"x": 50.0, "z": 50.0}} for q in have],
            "ready": [], "done": [],
        },
    }


def _gm():
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    gm.step_idx = 1
    return gm


def test_accept_offered_when_npc_has_quest_we_dont_have():
    """Измерено на живом мире 2026-08-24: рядом были Weaver Ottilie и Tinker
    Gizzel с 4 НЕВЗЯТЫМИ квестами, но accept_quest не предлагался, потому что
    условие смотрело на флаг accepted ОДНОГО выбранного квеста (а он был
    True — активных квестов 10). Итог: 'квесты не берёт'."""
    gm = _gm()
    info = _info(npc_quests=["q_new_a", "q_new_b"], have=["q_old"])
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "accept_quest" in cands, f"accept не предложен при новых квестах: {cands}"


def test_accept_not_offered_when_all_npc_quests_already_taken():
    """Обратная сторона: если у NPC только те квесты, что уже взяты — не
    предлагаем (иначе NPC ответит 'already taken' и шаг сгорит)."""
    gm = _gm()
    info = _info(npc_quests=["q_old"], have=["q_old"])
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "accept_quest" not in cands, f"accept предложен зря: {cands}"


def test_accept_offered_with_no_quests_at_all():
    gm = _gm()
    info = _info(npc_quests=["q_first"], have=[])
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="NO_QUEST")
    assert "accept_quest" in cands


def test_accept_not_offered_without_npc_nearby():
    gm = _gm()
    info = _info(npc_quests=(), have=["q_old"])
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "accept_quest" not in cands
