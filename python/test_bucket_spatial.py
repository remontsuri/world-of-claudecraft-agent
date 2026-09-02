"""RED test for state bucket spatial granularity.

We assert that two WorldStates that differ ONLY in the distance to the
nearest hostile mob produce DIFFERENT bucket keys. Today they produce the
same key (proved earlier: mob@5 == mob@40 == mob@80). This test will fail
until _bucket() is updated to include a 'near_mob' / 'mid_mob' feature.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from memory import _bucket


def _ws(nearest_mob_distance, distance_to_giver=20, in_combat=False, hp_frac=0.8):
    has_mob = nearest_mob_distance is not None
    return {
        "hp_frac": hp_frac,
        "quest_status": "ACTIVE",
        "has_mob": has_mob,
        "has_corpse": False,
        "has_junk": False,
        "danger": False,
        "distance_to_giver": distance_to_giver,
        "in_combat": in_combat,
        "strong_mob_near": False,
        "weak_mob_near": has_mob,
        "nearest_mob_distance": nearest_mob_distance,
    }


def test_bucket_distinguishes_mob_close_from_far():
    b5 = _bucket(_ws(5))
    b40 = _bucket(_ws(40))
    assert b5 != b40, f"RED CONFIRMED: bucket at mob@5yd == bucket at mob@40yd\n  b5 : {b5}\n  b40: {b40}"


def test_bucket_distinguishes_in_combat_from_out_of_combat_with_mob():
    b_in = _bucket(_ws(8, in_combat=True))
    b_out = _bucket(_ws(8, in_combat=False))
    assert b_in != b_out, f"RED: in_combat(T) == in_combat(F) at mob@8yd\n  in : {b_in}\n  out: {b_out}"


def test_bucket_distinguishes_no_mob_from_mid_mob():
    b_none = _bucket(_ws(None))
    b_mid = _bucket(_ws(15))
    assert b_none != b_mid, f"RED: no mob == mob@15yd\n  none: {b_none}\n  mid : {b_mid}"


def test_distinguishes_near_from_mid_mob():
    """mid (>7, <=25) is a different bucket from near (<=7) when has_mob."""
    b_near = _bucket(_ws(5))
    b_mid = _bucket(_ws(20))
    assert b_near != b_mid, (
        f"bucket(mob@5) should differ from bucket(mob@20): "
        f"agent must distinguish 'in melee range' from 'in chase range'.\n"
        f"  b_near: {b_near}\n  b_mid : {b_mid}"
    )


def test_distinguishes_mid_from_far_mob():
    """far (>25) is a different bucket from mid (<=25)."""
    b_mid = _bucket(_ws(20))
    b_far = _bucket(_ws(60))
    assert b_mid != b_far, (
        f"bucket(mob@20) should differ from bucket(mob@60): "
        f"agent must distinguish 'worth chasing' from 'out of reach'.\n"
        f"  b_mid: {b_mid}\n  b_far: {b_far}"
    )


def test_no_mob_bucket_includes_none():
    """When has_mob=False, mob_d='none' so the bucket differs from has_mob=True."""
    b_none = _bucket(_ws(None))
    assert "mob_d=none" in b_none, f"expected 'mob_d=none' in {b_none}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "-s"]))
