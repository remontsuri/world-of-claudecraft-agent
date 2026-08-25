"""test_nav_memory.py — TDD для nav_memory.py (план 2026-08-24, п.5).

Контракт: маршрут A->B по ячейкам; попытка/результат; is_stuck_route
по окну последних 5 попыток; save/load roundtrip; мусор не роняет.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))


def test_route_key_is_cell_stable():
    from nav_memory import route_key
    a = route_key([10.1, 20.2], [30.4, 40.6])
    b = route_key([10.9, 20.1], [30.1, 40.4])
    assert a == b, "близкие точки -> один ключ"
    c = route_key([50.0, 50.0], [60.0, 60.0])
    assert a != c


def test_route_key_garbage_safe():
    from nav_memory import route_key
    assert route_key(None, [1, 2]) is None
    assert route_key("x", "y") is None


def _tmp_mem(tmp_path):
    from nav_memory import NavMemory
    return NavMemory(path=os.path.join(str(tmp_path), "nav.json"))


def test_attempt_then_success(tmp_path):
    m = _tmp_mem(tmp_path)
    k = m.record_attempt([-10.0, -9.0], [-8.0, -18.0])
    assert k is not None
    m.record_result(k, success=True, dist_progress=12.0)
    st = m.route_stats([-10.0, -9.0], [-8.0, -18.0])
    assert st["attempts"] == 1
    assert st["success_rate"] == 1.0
    assert not m.is_stuck_route([-10.0, -9.0], [-8.0, -18.0])


def test_stuck_after_repeated_failures(tmp_path):
    m = _tmp_mem(tmp_path)
    pos_a, pos_b = [0.0, 0.0], [20.0, 20.0]
    for _ in range(5):
        k = m.record_attempt(pos_a, pos_b)
        m.record_result(k, success=False, dist_progress=0.1)
    assert m.is_stuck_route(pos_a, pos_b), "5 неудач подряд -> маршрут проблемный"


def test_not_stuck_with_mixed_results(tmp_path):
    m = _tmp_mem(tmp_path)
    pos_a, pos_b = [5.0, 5.0], [25.0, 25.0]
    results = [False, False, True, False, True]
    for s in results:
        k = m.record_attempt(pos_a, pos_b)
        m.record_result(k, success=s, dist_progress=3.0 if s else 0.2)
    assert not m.is_stuck_route(pos_a, pos_b), "2 успеха в окне -> не застряли"


def test_unknown_route_is_not_stuck(tmp_path):
    m = _tmp_mem(tmp_path)
    assert m.route_stats([1, 1], [2, 2]) is None
    assert not m.is_stuck_route([1, 1], [2, 2])


def test_save_load_roundtrip(tmp_path):
    p = os.path.join(str(tmp_path), "nav.json")
    from nav_memory import NavMemory
    m = NavMemory(path=p)
    k = m.record_attempt([1.0, 1.0], [9.0, 9.0])
    m.record_result(k, success=True, dist_progress=10.0)
    m.save()
    m2 = NavMemory(path=p)
    st = m2.route_stats([1.0, 1.0], [9.0, 9.0])
    assert st and st["attempts"] == 1


def test_eviction_under_cap():
    from nav_memory import NavMemory
    m = NavMemory(path=os.devnull, max_routes=5)
    for i in range(20):
        m.record_attempt([float(i), 0.0], [float(i + 100), 50.0])
    assert len(m.routes) <= 5 + 1  # cap + текущая
