"""Failing test for navigation reaching the turn-in NPC.

Reproduces the 'agent grinds against a wall / cannot pass' bug by calling the
live bridge navigate action toward the giver coord and asserting arrival.
Run: PYTHONPATH=. python _test_nav.py
"""
import json, urllib.request, sys


def post(action, payload=None, timeout=40):
    data = json.dumps({"action": action, **(payload or {})}).encode()
    req = urllib.request.Request("http://127.0.0.1:8791/", data=data,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def main():
    info = post("snapshot").get("info", {})
    giver = None
    for q in (info.get("quests", {}).get("active") or []):
        tn = q.get("turnInNpc")
        if tn and tn.get("x") is not None:
            giver = (tn["x"], tn["z"])
            break
    assert giver is not None, "no giver coord available in snapshot"
    print(f"giver target = {giver}")

    # Multi-leg navigate: if one call doesn't arrive, try a few more (agent
    # re-plans each step in reality; here we simulate a couple of retries).
    arrived = False
    for leg in range(3):
        r = post("navigate", {"x": giver[0], "z": giver[1], "max_steps": 80}, timeout=40)
        ok = r.get("ok")
        arr = r.get("arrived")
        pos = (r.get("info", {}) or {}).get("player_pos") or \
              (r.get("info", {}) or {}).get("player", {}).get("pos")
        print(f"leg {leg}: ok={ok} arrived={arr} pos={pos}")
        if arr:
            arrived = True
            break
    assert arrived, f"navigate did NOT reach giver {giver} after 3 legs (agent grinds wall)"
    print("PASS _test_nav: navigation reaches giver")


if __name__ == "__main__":
    try:
        main()
        print("\nNAV TEST PASS")
        sys.exit(0)
    except AssertionError as e:
        print(f"\nNAV TEST FAIL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nNAV TEST ERROR: {e}")
        sys.exit(1)
