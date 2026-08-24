import os, sys
sys.path.insert(0, os.path.dirname(__file__))


# ---------- Шаг 4: StrategyMemory считает ЗАВЕРШЕНИЕ, а не вердикты ----------

def _sm(tmp):
    from strategy_memory import StrategyMemory
    return StrategyMemory(path=os.path.join(tmp, "sm.json"))


def test_quest_completion_recorded_not_step_verdicts(tmp_path):
    """Найдено со-аудитором: record_outcome инкрементил success на КАЖДЫЙ
    SUCCESS-вердикт шага, поэтому у q_greyjaw накопилось 12024 «успеха» при
    нуле сдач, а best_skill стал sell_junk для квеста «убей волка».
    Теперь успех = ФАКТ завершения квеста."""
    sm = _sm(str(tmp_path))
    # 50 успешных шагов sell_junk НЕ должны делать его лучшим для квеста
    for _ in range(50):
        sm.record_step("quest:q_greyjaw", "sell_junk", True)
    assert sm.preference("quest:q_greyjaw") is None, (
        "шаговые вердикты не должны определять стратегию")
    # а одно РЕАЛЬНОЕ завершение на farm — должно
    sm.record_completion("quest:q_greyjaw", "farm")
    assert sm.preference("quest:q_greyjaw") == "farm"


def test_preference_needs_evidence_not_majority(tmp_path):
    """Второй дефект: preference() возвращала best_skill только при
    success > fail, поэтому даже при живом чтении отдавала None.
    Теперь достаточно ДОКАЗАННЫХ завершений."""
    sm = _sm(str(tmp_path))
    sm.record_completion("quest:q_a", "turn_in_quest")
    assert sm.preference("quest:q_a") == "turn_in_quest"


def test_most_completed_skill_wins(tmp_path):
    sm = _sm(str(tmp_path))
    for _ in range(3):
        sm.record_completion("quest:q_a", "farm")
    sm.record_completion("quest:q_a", "gather")
    assert sm.preference("quest:q_a") == "farm"


def test_boost_multiplier_scales_with_evidence(tmp_path):
    """Приёмка A2: доказанный скилл получает множитель веса ≥1.5."""
    from strategy_memory import StrategyMemory, STRATEGY_BOOST
    sm = _sm(str(tmp_path))
    assert sm.boost("quest:q_a", "farm") == 1.0, "без доказательств буста нет"
    for _ in range(3):
        sm.record_completion("quest:q_a", "farm")
    assert sm.boost("quest:q_a", "farm") >= 1.5, "доказанный скилл должен буститься"
    assert sm.boost("quest:q_a", "gather") == 1.0, "другие скиллы не буститься"
    assert STRATEGY_BOOST >= 1.5


def test_persists_across_instances(tmp_path):
    from strategy_memory import StrategyMemory
    p = os.path.join(str(tmp_path), "sm.json")
    a = StrategyMemory(path=p)
    a.record_completion("quest:q_a", "farm")
    a.save()
    b = StrategyMemory(path=p)
    assert b.preference("quest:q_a") == "farm"


# ---------- Шаг 4b: StrategyMemory ЧИТАЕТСЯ при выборе действия ----------

def test_policy_reads_strategy_memory(tmp_path):
    """Ключевая приёмка A2: раньше StrategyMemory была write-only —
    .preference() вызывался ТОЛЬКО в смоук-тесте. Теперь политика обязана
    учитывать доказанную стратегию при выборе действия."""
    from policy import GoalManager
    from memory import ExperienceStore
    from strategy_memory import StrategyMemory
    sm = StrategyMemory(path=os.path.join(str(tmp_path), "sm.json"))
    for _ in range(3):
        sm.record_completion("quest:q_bones", "farm")
    gm = GoalManager(ExperienceStore(), reflection_hints={}, strategy_memory=sm)
    assert gm.strategy_memory is sm, "политика должна принимать StrategyMemory"
    info = {
        "player": {"hp": 100, "maxHp": 100, "dead": False},
        "player_pos": [0.0, 0.0], "inventory": [],
        "nearby": [{"id": 1, "kind": "mob", "type": "mob", "name": "wolf",
                    "dist": 8.0, "hp": 30, "maxHp": 30}],
        "quests": {"active": [{"id": "q_bones", "state": "active",
                               "objectives": [{"current": 1, "required": 8}]}],
                   "ready": [], "done": []},
    }
    ws = gm._world_state(info)
    vals = gm._strategy_weighted({"farm": 1.0, "loot": 1.0}, info, ws)
    assert vals["farm"] > vals["loot"], (
        f"доказанный farm должен весить больше: {vals}")


def test_no_strategy_memory_is_safe():
    """Без StrategyMemory политика работает как раньше (обратная совместимость)."""
    from policy import GoalManager
    from memory import ExperienceStore
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    vals = gm._strategy_weighted({"farm": 1.0, "loot": 1.0}, {}, {})
    assert vals == {"farm": 1.0, "loot": 1.0}
