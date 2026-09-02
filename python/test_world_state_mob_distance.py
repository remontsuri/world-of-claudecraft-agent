"""Integration test: world_state.build_world_state populates
`nearest_mob_distance` from info.nearby so memory._bucket's `mob_d` band works.
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
from world_state import build_world_state
from memory import _bucket


def _info(player_pos, mobs):
    """Build a minimal `info` dict with player at player_pos and `mobs` nearby.

    Each mob: {kind:'mob', hostile:true, dead:false, hp:10, maxHp:10, x, z}
    """
    return {
        "player": {"hp": 100, "maxHp": 100, "level": 1, "facing": 0},
        "player_pos": list(player_pos),
        "nearby": [{"kind": "mob", "hostile": True, "dead": False, "hp": 10, "maxHp": 10,
                    "lootable": False, **m} for m in mobs],
    }


def test_nearest_mob_distance_close_mob():
    info = _info([0, 0], [{"x": 3, "z": 4}])  # dist=5
    ws = build_world_state(info)
    assert ws["nearest_mob_distance"] == 5.0, f"expected 5.0, got {ws['nearest_mob_distance']}"
    assert ws["has_mob"] is True
    bucket = _bucket(ws)
    assert "mob_d=near" in bucket, f"expected mob_d=near, got {bucket}"


def test_nearest_mob_distance_mid_mob():
    info = _info([0, 0], [{"x": 0, "z": 20}])  # dist=20
    ws = build_world_state(info)
    assert 19.9 < ws["nearest_mob_distance"] < 20.1
    bucket = _bucket(ws)
    assert "mob_d=mid" in bucket, f"expected mob_d=mid, got {bucket}"


def test_nearest_mob_distance_far_mob():
    info = _info([0, 0], [{"x": 0, "z": 60}])  # dist=60
    ws = build_world_state(info)
    assert 59.9 < ws["nearest_mob_distance"] < 60.1
    bucket = _bucket(ws)
    assert "mob_d=far" in bucket, f"expected mob_d=far, got {bucket}"


def test_nearest_mob_distance_no_mobs():
    info = _info([0, 0], [])
    ws = build_world_state(info)
    assert ws["nearest_mob_distance"] is None
    bucket = _bucket(ws)
    assert "mob_d=none" in bucket, f"expected mob_d=none, got {bucket}"


def test_nearest_mob_distance_ignores_dead_mobs():
    info = _info([0, 0], [
        {"x": 0, "z": 5, "dead": True, "hp": 0},     # 5yd, dead — ignored
        {"x": 0, "z": 20, "dead": False, "hp": 10},  # 20yd, live
    ])
    ws = build_world_state(info)
    assert 19.9 < ws["nearest_mob_distance"] < 20.1, (
        f"nearest should be 20 (the live one), not 5 (the dead one); got {ws['nearest_mob_distance']}"
    )


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-s"]))
