import os, sys
sys.path.insert(0, os.path.dirname(__file__))


# ---------- Шаг 3: Event Bus доходит до рефлексии ----------

def test_reflection_accepts_events():
    """Шаг 3 спеки: event_bus был мёртв — 9 типов событий не доходили ни до
    награды, ни до рефлексии (аудит: 'только свой файл + unit-тест')."""
    from self_reflection import SelfReflection
    import tempfile
    r = SelfReflection(dirpath=tempfile.mkdtemp())
    assert hasattr(r, "observe_events"), "рефлексия должна принимать события"
    r.observe_events([{"type": "PlayerDied", "deaths": 3}])
    assert len(r.recent_events) == 1


def test_navigation_stuck_event_creates_hint():
    """Правило NAVIGATION_STUCK: застревание -> вербальный урок -> подавление."""
    from self_reflection import SelfReflection
    import tempfile
    r = SelfReflection(dirpath=tempfile.mkdtemp())
    r.observe_events([{"type": "NavigationStuck", "frames": 8, "pos": [1.0, 2.0]}])
    hints = r.event_conclusions()
    keys = [h["key"] for h in hints]
    assert any(k.startswith("stuck:") for k in keys), f"нет вывода о застревании: {keys}"


def test_inventory_full_event_creates_hint():
    """Правило INVENTORY_FULL_PRESSURE: полные сумки блокируют сдачу квеста."""
    from self_reflection import SelfReflection
    import tempfile
    r = SelfReflection(dirpath=tempfile.mkdtemp())
    r.observe_events([{"type": "InventoryFull"}])
    hints = r.event_conclusions()
    assert any(h["key"] == "bags:full" for h in hints), hints


def test_quest_completed_event_creates_positive_hint():
    """Правило QUEST_COMPLETED_THEN_IDLE: закончил — бери следующий."""
    from self_reflection import SelfReflection
    import tempfile
    r = SelfReflection(dirpath=tempfile.mkdtemp())
    r.observe_events([{"type": "QuestCompleted", "quest_id": "q_bones"}])
    hints = r.event_conclusions()
    assert any(h["key"] == "quest:completed" for h in hints), hints


def test_events_window_is_bounded():
    """Reflexion: буфер ограничен (1-3 свежих вывода), иначе контекст растёт."""
    from self_reflection import SelfReflection, EVENT_WINDOW
    import tempfile
    r = SelfReflection(dirpath=tempfile.mkdtemp())
    for i in range(EVENT_WINDOW + 30):
        r.observe_events([{"type": "DamageTaken", "amount": i}])
    assert len(r.recent_events) <= EVENT_WINDOW, len(r.recent_events)


def test_no_events_no_conclusions():
    from self_reflection import SelfReflection
    import tempfile
    r = SelfReflection(dirpath=tempfile.mkdtemp())
    assert r.event_conclusions() == []


# ---------- Шаг 5: хинты stall:/cycle:/stuck:/bags: реально применяются ----------

def test_stuck_hint_suppresses_action():
    """Аудит: ключи stall:/cycle: загружались, но НИКОГДА не применялись
    (policy.py:413-421 знал только spin:/death:). Теперь применяются."""
    from policy import GoalManager
    from memory import ExperienceStore
    hints = {"stuck:return_to_giver": {"kind": "NAVIGATION_STUCK",
                                       "detail": "стоим на месте",
                                       "hint": "reduce_weight"}}
    gm = GoalManager(ExperienceStore(), reflection_hints=hints)
    info = {"player": {"hp": 100, "maxHp": 100, "dead": False},
            "player_pos": [0.0, 0.0], "inventory": [], "nearby": [],
            "quests": {"active": [{"id": "q_a", "state": "active",
                                   "objectives": [{"current": 1, "required": 2}],
                                   "turnInNpc": {"x": 3.0, "z": 4.0}}],
                       "ready": [], "done": []}}
    ws = gm._world_state(info)
    gm._candidates(info, ws, goal="RETURN_TO_GIVER")
    assert "return_to_giver" in gm._suppressed, (
        f"stuck-хинт не подавил скилл: {gm._suppressed}")


def test_bags_full_hint_boosts_selling():
    """Правило про полные сумки должно ПОВЫШАТЬ продажу, а не подавлять."""
    from policy import GoalManager
    from memory import ExperienceStore
    hints = {"bags:full": {"kind": "INVENTORY_FULL", "detail": "сумки полны",
                           "hint": "prefer_sell"}}
    gm = GoalManager(ExperienceStore(), reflection_hints=hints)
    assert "sell_junk" in gm._preferred_from_hints(), gm._preferred_from_hints()
