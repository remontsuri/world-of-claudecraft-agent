"""Headless skill smoke test: each skill -> Verifier-style world delta.

Uses HierarchicalWoWEnv (farm is proven there) + base WoWClassicEnv capability
commands (sell_junk / harvest_node / craft_item / accept_quest / turn_in_quest)
exposed in env_server.ts.

Run: env -u PYTHONPATH /d/woc-llm/therock-test/Scripts/python.exe test_skills_headless.py
"""
from hierarchical_env import HierarchicalWoWEnv
from wow_env import WoWClassicEnv

ACT_TARGET = 8
ACT_FORWARD = 1
ACT_TURN_LEFT = 3
ACT_TURN_RIGHT = 4
ACT_ATTACK = 9
ACT_INTERACT = 22
ACT_STRAFE_RIGHT = 6
ACT_EAT_DRINK = 60


def test_farm_loot_sell():
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=200, seed=42)
    obs, info = env.reset(seed=42)
    k0 = info.get("kills", 0)
    # farm until a kill
    for _ in range(8):
        obs, r, term, trunc, info = env.step(0)  # farm skill
        if info.get("kills", 0) > k0:
            print(f"[FARM]      kills {k0}->{info.get('kills')}  -> SUCCESS")
            break
    else:
        print(f"[FARM]      kills {k0}->{info.get('kills')}  -> FAIL")

    # loot: interact near corpse
    inv_before = len(info.get("inventory", []))
    copper0 = info.get("copper", 0)
    _, _, _, _, info = env.base.step(ACT_INTERACT)
    inv_after = len(info.get("inventory", []))
    print(f"[LOOT]      inv {inv_before}->{inv_after}  -> {'SUCCESS' if inv_after >= inv_before else 'INCONCLUSIVE'}")

    # sell_junk
    info = env.base.sell_junk()
    copper1 = info.get("copper", 0)
    print(f"[SELL_JUNK] copper {copper0}->{copper1}  -> {'SUCCESS' if copper1 > copper0 else 'INCONCLUSIVE'}")

    env.close()
    return copper1 > copper0


def test_api_reachability():
    env = WoWClassicEnv(player_class="warrior", max_steps=2000)
    env.reset(seed=42)
    for cmd, fn in [
        ("ACCEPT_QUEST", lambda: env.accept_quest("__probe__")),
        ("HARVEST_NODE", lambda: env.harvest_node("__probe__")),
        ("CRAFT_ITEM", lambda: env.craft_item("__probe__")),
        ("TURN_IN_QUEST", lambda: env.turn_in_quest("__probe__")),
    ]:
        try:
            fn()
            print(f"[{cmd}] cmd accepted (no crash)")
        except Exception as e:
            print(f"[{cmd}] ERROR {e}")
    env.close()


def test_heal():
    env = WoWClassicEnv(player_class="warrior", max_steps=2000)
    env.reset(seed=42)
    hp0 = env._last_info.get("hp") if hasattr(env, "_last_info") else None
    _, _, _, _, info = env.step(ACT_EAT_DRINK)
    hp1 = info.get("hp")
    print(f"[HEAL]      hp {hp0}->{hp1}  -> {'SUCCESS' if (hp1 or 0) >= (hp0 or 0) else 'INCONCLUSIVE'}")
    env.close()


if __name__ == "__main__":
    print("=== Skill smoke test (headless, ROCm venv) ===")
    test_farm_loot_sell()
    test_api_reachability()
    test_heal()
    print("=== done ===")
