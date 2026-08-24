import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def test_anchor_records_position_when_object_present():
    """Шаг #3 (Q6, консенсус): агент запоминает позицию, где были объекты
    действия (мобы/трупы/узлы/гиверы). Измерено: агент ушёл на [-13, 275],
    где нет ничего, и 25 шагов бил в пустоту."""
    from work_anchor import WorkAnchor
    import tempfile
    a = WorkAnchor(path=os.path.join(tempfile.mkdtemp(), "anchor.json"))
    info = {"player_pos": [10.0, 20.0],
            "nearby": [{"kind": "mob", "dead": False, "dist": 12.0,
                        "hp": 40, "maxHp": 40}]}
    a.observe(info)
    assert a.last_work_pos == [10.0, 20.0]


def test_anchor_ignores_empty_surroundings():
    """Пустая позиция не должна становиться якорем — иначе запомним пустоту."""
    from work_anchor import WorkAnchor
    import tempfile
    a = WorkAnchor(path=os.path.join(tempfile.mkdtemp(), "anchor.json"))
    a.observe({"player_pos": [1.0, 1.0],
               "nearby": [{"kind": "mob", "dead": False, "dist": 12.0,
                           "hp": 40, "maxHp": 40}]})
    a.observe({"player_pos": [-13.0, 275.0], "nearby": []})   # пустота
    assert a.last_work_pos == [1.0, 1.0], "якорь перезаписан пустой позицией"


def test_needs_return_when_far_and_nothing_around():
    from work_anchor import WorkAnchor
    import tempfile
    a = WorkAnchor(path=os.path.join(tempfile.mkdtemp(), "anchor.json"))
    a.observe({"player_pos": [0.0, 0.0],
               "nearby": [{"kind": "mob", "dead": False, "dist": 10.0,
                           "hp": 40, "maxHp": 40}]})
    far = {"player_pos": [-13.0, 275.0], "nearby": []}
    assert a.needs_return(far) is True


def test_no_return_when_objects_are_around():
    from work_anchor import WorkAnchor
    import tempfile
    a = WorkAnchor(path=os.path.join(tempfile.mkdtemp(), "anchor.json"))
    a.observe({"player_pos": [0.0, 0.0],
               "nearby": [{"kind": "mob", "dead": False, "dist": 10.0,
                           "hp": 40, "maxHp": 40}]})
    here = {"player_pos": [200.0, 200.0],
            "nearby": [{"kind": "mob", "dead": False, "dist": 8.0,
                        "hp": 40, "maxHp": 40}]}
    assert a.needs_return(here) is False, "объекты рядом — возвращаться не нужно"


def test_target_falls_back_to_quest_giver():
    """Если якоря ещё нет, цель возврата — гивер активного квеста."""
    from work_anchor import WorkAnchor
    import tempfile
    a = WorkAnchor(path=os.path.join(tempfile.mkdtemp(), "anchor.json"))
    info = {"player_pos": [-13.0, 275.0], "nearby": [],
            "quests": {"active": [{"id": "q_a",
                                   "turnInNpc": {"x": 4.0, "z": -56.0}}],
                       "ready": []}}
    assert a.return_target(info) == [4.0, -56.0]


def test_target_prefers_anchor_over_giver():
    from work_anchor import WorkAnchor
    import tempfile
    a = WorkAnchor(path=os.path.join(tempfile.mkdtemp(), "anchor.json"))
    a.observe({"player_pos": [7.0, 8.0],
               "nearby": [{"kind": "mob", "dead": False, "dist": 5.0,
                           "hp": 40, "maxHp": 40}]})
    info = {"player_pos": [-13.0, 275.0], "nearby": [],
            "quests": {"active": [{"id": "q_a",
                                   "turnInNpc": {"x": 4.0, "z": -56.0}}],
                       "ready": []}}
    assert a.return_target(info) == [7.0, 8.0]


def test_anchor_persists_across_instances():
    from work_anchor import WorkAnchor
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "anchor.json")
    a = WorkAnchor(path=p)
    a.observe({"player_pos": [3.0, 4.0],
               "nearby": [{"kind": "mob", "dead": False, "dist": 5.0,
                           "hp": 40, "maxHp": 40}]})
    a.save()
    b = WorkAnchor(path=p)
    assert b.last_work_pos == [3.0, 4.0]
