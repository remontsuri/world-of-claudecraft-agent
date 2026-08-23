import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _hints(*keys):
    return {f"spin:{k}": {"kind": "ACTION_SATURATION",
                          "detail": f"'{k}' spinning", "hint": "reduce_weight"}
            for k in keys}


def _info(hp=142, max_hp=142):
    return {
        "player": {"hp": hp, "maxHp": max_hp, "dead": False},
        "player_pos": [0, 0],
        "nearby": [{"id": 1, "kind": "mob", "type": "mob", "name": "wolf",
                    "dist": 30, "hp": 50, "maxHp": 50}],
        "inventory": [],
        "quests": {
            "active": [{"id": "q_x", "state": "active",
                        "objectives": [{"current": 5, "required": 6}],
                        "turnInNpc": {"x": 5.0, "z": 5.0}}],
            "ready": [{"id": "q_ready", "state": "ready",
                       "objectives": [{"current": 8, "required": 8}],
                       "turnInNpc": {"x": 5.0, "z": 5.0}}],
            "done": [],
        },
    }


def test_spin_hint_does_not_remove_action_from_candidates():
    """Найдено со-архитектором 2026-08-24: policy делал cands.remove(bad) —
    жёсткое удаление, хотя контракт обещает подавление веса x0.3. Из-за этого
    spin:return_to_giver физически вырезал скилл, и детерминированный override
    фазы RETURN_TO_GIVER никогда не срабатывал (turn_in=0 за 1288 шагов)."""
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints=_hints("return_to_giver"))
    info = _info()
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="RETURN_TO_GIVER")
    assert "return_to_giver" in cands, (
        f"spin-хинт не должен УДАЛЯТЬ скилл, только подавлять вес: {cands}")


def test_spin_hint_suppresses_weight_not_membership():
    """Подавление должно жить в весах: скилл остаётся кандидатом, но его вес
    умножается на SPIN_WEIGHT_MULT."""
    from policy import GoalManager, SPIN_WEIGHT_MULT
    from memory import ExperienceStore
    assert 0.0 < SPIN_WEIGHT_MULT < 1.0
    gm = GoalManager(ExperienceStore(), reflection_hints=_hints("heal"))
    info = _info(hp=60)
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "heal" in cands


def test_deterministic_override_survives_spin_hint():
    """Ключевой регресс: при spin:return_to_giver фаза RETURN_TO_GIVER всё равно
    обязана детерминированно выбрать return_to_giver."""
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints=_hints("return_to_giver"))
    info = _info()
    ws = gm._world_state(info)
    action, ctx = gm.decide(info, ws=ws, goal="RETURN_TO_GIVER")
    assert action == "return_to_giver", f"got {action}"


def test_multiple_spin_hints_keep_every_action_available():
    """Даже когда ВСЕ доступные скиллы под spin-хинтами, набор кандидатов не
    должен схлопываться: подавление живёт в весах. Берём hp<1.0, чтобы heal
    был легальным кандидатом (при полном hp его не предлагают)."""
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(),
                     reflection_hints=_hints("heal", "return_to_giver", "farm"))
    info = _info(hp=60)
    ws = gm._world_state(info)
    cands = gm._candidates(info, ws, goal="DO_OBJECTIVE")
    assert "farm" in cands, f"farm вырезан хинтом: {cands}"
    assert "heal" in cands, f"heal вырезан хинтом: {cands}"
    # и подавление зафиксировано, а не потеряно
    assert {"farm", "heal"} <= gm._suppressed
