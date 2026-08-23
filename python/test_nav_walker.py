import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from nav_policy import plan_leg, execute


def test_plan_forward_when_aimed():
    # игрок в [0,0], facing 0 (+Z), цель прямо впереди [0,10]
    p = plan_leg([0, 0], [0, 10], facing=0.0)
    assert p is not None
    assert p["turns"] == 0 and p["forward_ticks"] > 0
    assert p["jump"] is True          # fence-hop pulse on straight legs


def test_plan_turns_toward_offset_target():
    # цель на востоке (x+10): desired = atan2(10,0)= +pi/2 -> нужен turnLeft (+1)
    p = plan_leg([0, 0], [10, 0], facing=0.0)
    assert p["turns"] == 1 and p["turn_ticks"] >= 1


def test_plan_turns_right_when_negative():
    # цель на западе: desired = -pi/2 -> turnRight (-1)
    p = plan_leg([0, 0], [-10, 0], facing=0.0)
    assert p["turns"] == -1 and p["turn_ticks"] >= 1


def test_arrived_returns_none():
    assert plan_leg([0, 0], [2, 2], facing=0.0, arrive_dist=4.0) is None


def test_execute_walks_and_reads_pos():
    class FakeEnv:
        def __init__(self):
            self.pos = [0.0, 0.0]
            self.moves = []
            self._last_info = {"player_pos": self.pos}
        def _raw_move(self, kind):
            self.moves.append(kind)
            if kind == "forward":
                self.pos[1] += 1.5       # facing 0 -> +Z
            elif kind == "turnLeft":
                pass                      # упрощение для теста
            self._last_info = {"player_pos": list(self.pos)}
    e = FakeEnv()
    pos = execute(e, [0, 0], [0, 9], facing=0.0, legs=3, arrive_dist=4.0)
    assert "forward" in e.moves
    assert pos[1] > 4.0                   # реально приблизился
