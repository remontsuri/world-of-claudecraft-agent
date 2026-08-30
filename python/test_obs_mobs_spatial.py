"""Milestone 1 — spatial mob observation (RED then GREEN).

Contract (per user 2026-08-30): obs["mobs"] must carry a per-mob
spatial vector so the policy can LEARN navigation, not be scripted:

    obs["mobs"] = [
      {
        "dx": ...,            # mob.x - player.x  (relative, from game only)
        "dz": ...,            # mob.z - player.z
        "distance": ...,      # hypot(dx, dz)
        "angle": ...,         # bearing relative to player FACING, not world 0
        "hp": ...,
        "hostile": ...,
        "quest_target": ...,  # True if this mob matches the active kill objective
      },
      ...
    ]

Source: exclusively info["nearby"] / canonical ws — NO static tables.
This is observation, not a navigation command.

Run: python test_obs_mobs_spatial.py
"""
import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from observation import encode_observation


def _ws_with_mobs(player_facing=0.0):
    """Minimal ws/info carrying two live mobs near the player."""
    info = {
        "player": {
            "hp": 100, "maxHp": 100, "facing": player_facing,
            "pos": {"x": 10.0, "z": 20.0},
        },
        "player_pos": [10.0, 20.0],
        "nearby": [
            # mob directly EAST of player (world +x), 5 yd away
            {"id": 1, "kind": "mob", "templateId": "forest_wolf",
             "x": 15.0, "z": 20.0, "hp": 40, "maxHp": 40,
             "hostile": True, "dead": False},
            # mob NORTH-EAST, 10 yd away, NOT the quest target
            {"id": 2, "kind": "mob", "templateId": "boar",
             "x": 17.0, "z": 27.0, "hp": 30, "maxHp": 30,
             "hostile": True, "dead": False},
            # a dead mob — must be excluded
            {"id": 3, "kind": "mob", "templateId": "forest_wolf",
             "x": 12.0, "z": 22.0, "hp": 0, "hostile": True, "dead": True},
        ],
    }
    # active kill objective: forest_wolf
    ws = {
        "player": info["player"],
        "player_pos": info["player_pos"],
        "hp_frac": 1.0,
        "quests": {"active": [{
            "id": "q_wolves",
            "objectives": [{
                "type": "kill", "targetMobId": "forest_wolf",
                "current": 3, "required": 8,
            }],
        }]},
        "quest": {"id": "q_wolves", "objectives": [
            {"type": "kill", "targetMobId": "forest_wolf",
             "current": 3, "required": 8}]},
    }
    return ws, info


def test_mobs_present_with_spatial_fields():
    ws, info = _ws_with_mobs()
    obs = encode_observation(ws, info)
    mobs = obs.get("mobs")
    assert isinstance(mobs, list), f"obs['mobs'] must be a list, got {type(mobs)}"
    # dead mob excluded -> 2 live mobs
    assert len(mobs) == 2, f"expected 2 live mobs, got {len(mobs)}"
    for m in mobs:
        for key in ("dx", "dz", "distance", "angle", "hp", "hostile",
                    "quest_target"):
            assert key in m, f"mob vector missing '{key}': {m}"
    print("GREEN: obs['mobs'] present with dx/dz/distance/angle/hp/hostile/quest_target")


def test_dx_dz_relative_to_player():
    ws, info = _ws_with_mobs()
    obs = encode_observation(ws, info)
    mobs = obs["mobs"]
    # mob id=1 at (15,20), player at (10,20) -> dx=+5, dz=0
    m1 = next(m for m in mobs if m["dx"] == 5.0 or abs(m["dx"] - 5.0) < 1e-6)
    assert abs(m1["dx"] - 5.0) < 1e-6, f"expected dx=5.0, got {m1['dx']}"
    assert abs(m1["dz"] - 0.0) < 1e-6, f"expected dz=0.0, got {m1['dz']}"
    assert abs(m1["distance"] - 5.0) < 1e-6, f"expected dist=5.0, got {m1['distance']}"
    print("GREEN: dx/dz relative to player (mob.x - player.x)")


def test_angle_relative_to_facing_not_world_zero():
    # _bearing_of uses atan2(dx, dz): 0 = +z (north), +pi/2 = +x (east).
    # mob id=1 is due EAST (dx=+5, dz=0) -> world bearing = +pi/2.
    # player faces EAST (facing=+pi/2) -> relative angle ~ 0 (mob ahead)
    ws, info = _ws_with_mobs(player_facing=math.pi / 2)
    obs = encode_observation(ws, info)
    m1 = next(m for m in obs["mobs"] if abs(m["dx"] - 5.0) < 1e-6)
    assert abs(m1["angle"]) < 1e-3, f"expected angle~0 (mob ahead), got {m1['angle']}"

    # now face NORTH (facing=0): mob due east is +pi/2 relative
    ws2, info2 = _ws_with_mobs(player_facing=0.0)
    obs2 = encode_observation(ws2, info2)
    m1b = next(m for m in obs2["mobs"] if abs(m["dx"] - 5.0) < 1e-6)
    assert abs(m1b["angle"] - (math.pi / 2)) < 1e-3, (
        f"expected angle=+pi/2 when facing north, got {m1b['angle']}"
    )
    print("GREEN: angle relative to player facing (not world zero)")


def test_quest_target_flag():
    ws, info = _ws_with_mobs()
    obs = encode_observation(ws, info)
    mobs = obs["mobs"]
    wolf = next(m for m in mobs if m["dx"] == 5.0)
    boar = next(m for m in mobs if m["dx"] != 5.0)
    assert wolf["quest_target"] is True, "forest_wolf should be quest_target"
    assert boar["quest_target"] is False, "boar should NOT be quest_target"
    print("GREEN: quest_target flag matches active kill objective")


if __name__ == "__main__":
    test_mobs_present_with_spatial_fields()
    test_dx_dz_relative_to_player()
    test_angle_relative_to_facing_not_world_zero()
    test_quest_target_flag()
    print("ALL GREEN")
