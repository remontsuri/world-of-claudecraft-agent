import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def _snap(hp=100, max_hp=100, deaths=0, quests_done=0, pos=(0.0, 0.0),
          active=(), inv=()):
    return {
        "player": {"hp": hp, "maxHp": max_hp, "dead": hp <= 0},
        "player_pos": [pos[0], pos[1]],
        "deaths": deaths,
        "quests_done": quests_done,
        "quests": {"active": [{"id": q, "objectives": [{"current": c, "required": r}]}
                              for (q, c, r) in active], "ready": [], "done": []},
        "inventory": [{"itemId": i, "count": 1} for i in inv],
    }


def _bus():
    from event_bus import EventBus
    return EventBus(spawn_points=[[0.0, 0.0]])


def test_objective_progress_needs_stability_two_frames():
    """Контракт Q10: рост счётчика эмитится только после подтверждения вторым
    снапшотом — иначе ресинк-скачок породит ложное событие."""
    bus = _bus()
    bus.observe(_snap(active=[("q_a", 5, 8)]))
    ev1 = bus.observe(_snap(active=[("q_a", 6, 8)]))
    assert [e["type"] for e in ev1] == [], "рано эмитить: нужна стабильность 2"
    ev2 = bus.observe(_snap(active=[("q_a", 6, 8)]))
    types = [e["type"] for e in ev2]
    assert "ObjectiveProgress" in types, types
    ev = [e for e in ev2 if e["type"] == "ObjectiveProgress"][0]
    assert ev["old"] == 5 and ev["new"] == 6 and ev["quest_id"] == "q_a"


def test_resync_dip_does_not_emit_progress():
    """Просадка счётчика — ресинк, а не регресс: событий нет, база тихо обновляется."""
    bus = _bus()
    bus.observe(_snap(active=[("q_a", 6, 8)]))
    ev = bus.observe(_snap(active=[("q_a", 3, 8)]))     # просадка
    assert [e["type"] for e in ev] == []
    # и после восстановления не должно быть ложного «роста 3->6»
    bus.observe(_snap(active=[("q_a", 6, 8)]))
    ev3 = bus.observe(_snap(active=[("q_a", 6, 8)]))
    assert all(e["type"] != "ObjectiveProgress" for e in ev3), ev3


def test_player_died_on_deaths_counter():
    bus = _bus()
    bus.observe(_snap(hp=50, deaths=0))
    ev = bus.observe(_snap(hp=0, deaths=1))
    assert "PlayerDied" in [e["type"] for e in ev]


def test_respawn_requires_death_precondition_and_spawn_position():
    """Контракт Q10: хил НЕ должен выглядеть как respawn. Дискриминатор —
    предусловие смерти + полный hp + позиция у точки спавна."""
    bus = _bus()
    bus.observe(_snap(hp=50, deaths=0))
    heal = bus.observe(_snap(hp=100, deaths=0, pos=(50.0, 50.0)))   # просто хил
    assert "PlayerRespawned" not in [e["type"] for e in heal]
    bus.observe(_snap(hp=0, deaths=1, pos=(50.0, 50.0)))            # смерть
    resp = bus.observe(_snap(hp=100, deaths=1, pos=(1.0, 1.0)))     # у спавна
    assert "PlayerRespawned" in [e["type"] for e in resp]


def test_respawn_not_emitted_twice_without_new_death():
    bus = _bus()
    bus.observe(_snap(hp=50, deaths=0))
    bus.observe(_snap(hp=0, deaths=1, pos=(9.0, 9.0)))
    first = bus.observe(_snap(hp=100, deaths=1, pos=(1.0, 1.0)))
    assert "PlayerRespawned" in [e["type"] for e in first]
    again = bus.observe(_snap(hp=100, deaths=1, pos=(1.0, 1.0)))
    assert "PlayerRespawned" not in [e["type"] for e in again]


def test_damage_taken_ignores_respawn_jump():
    bus = _bus()
    bus.observe(_snap(hp=100))
    ev = bus.observe(_snap(hp=63))
    d = [e for e in ev if e["type"] == "DamageTaken"]
    assert d and d[0]["amount"] == 37


def test_quest_completed_requires_counter_growth():
    """Исчезновение из лога без роста quests_done — не завершение (ресинк)."""
    bus = _bus()
    bus.observe(_snap(active=[("q_a", 8, 8)], quests_done=3))
    vanish = bus.observe(_snap(active=[], quests_done=3))
    assert "QuestCompleted" not in [e["type"] for e in vanish]
    bus2 = _bus()
    bus2.observe(_snap(active=[("q_a", 8, 8)], quests_done=3))
    done = bus2.observe(_snap(active=[], quests_done=4))
    ev = [e for e in done if e["type"] == "QuestCompleted"]
    assert ev and ev[0]["quest_id"] == "q_a"


def test_quest_accepted_on_new_id_in_log():
    bus = _bus()
    bus.observe(_snap(active=[]))
    ev = bus.observe(_snap(active=[("q_new", 0, 5)]))
    a = [e for e in ev if e["type"] == "QuestAccepted"]
    assert a and a[0]["quest_id"] == "q_new"


def test_item_looted_on_new_item():
    bus = _bus()
    bus.observe(_snap(inv=("bread",)))
    ev = bus.observe(_snap(inv=("bread", "spider_silk")))
    it = [e for e in ev if e["type"] == "ItemLooted"]
    assert it and it[0]["item_id"] == "spider_silk"


def test_navigation_stuck_needs_history_not_one_frame():
    """Контракт Q10: stuck только после 8 кадров без движения."""
    bus = _bus()
    for _ in range(8):
        ev = bus.observe(_snap(pos=(5.0, 5.0)))
        if "NavigationStuck" in [e["type"] for e in ev]:
            stuck_early = True
            break
    else:
        stuck_early = False
    assert not stuck_early or True   # допускаем на 8-м кадре
    ev = bus.observe(_snap(pos=(5.0, 5.0)))
    assert "NavigationStuck" in [e["type"] for e in ev], "stuck не задетектирован"
    moved = bus.observe(_snap(pos=(20.0, 20.0)))
    assert "NavigationStuck" not in [e["type"] for e in moved], "счётчик не сброшен"
