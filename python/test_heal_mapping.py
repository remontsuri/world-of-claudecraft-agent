"""
RED -> GREEN: ACT_EAT_DRINK must map to bridge case 7 (heal), NOT idx 60 (no-op).

Root cause (2026-08-30, live-proven):
- hierarchical_env.ACT_EAT_DRINK = 60
- but bridge actions.cjs has NO case 60 -> step(idx=60) is a silent no-op
  (bridge returns ok:true without healing). So heal never restored HP and
  the agent spiralled (211x heal_rejected, hp yoyo 1.0 -> 0.2 -> death).
- bridge case 7 = heal (uses potion/food, then must wait for out-of-combat
  regen since the game auto-regens HP when not in combat).

The game auto-regens HP out of combat (measured: 50 -> 95 over 10s), so
heal does NOT need food — it needs to exit combat and let regen run.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hierarchical_env as he


def test_act_eat_drink_maps_to_bridge_heal():
    # bridge case 7 = heal (actions.cjs case 7)
    assert he.ACT_EAT_DRINK == 7, (
        f"ACT_EAT_DRINK={he.ACT_EAT_DRINK}, must be 7 (bridge case 7 = heal). "
        f"idx 60 is a silent no-op -> heal never restores HP."
    )


if __name__ == "__main__":
    try:
        test_act_eat_drink_maps_to_bridge_heal()
        print("GREEN: ACT_EAT_DRINK maps to bridge heal (case 7)")
    except AssertionError as e:
        print("RED:", e)
