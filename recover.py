"""Recovery script - walk to spirit healer and resurrect when dead."""
import json, time, urllib.request, math

BRIDGE = "http://127.0.0.1:8791/"

def call(action, data=None):
    payload = {"action": action}
    if data:
        payload.update(data)
    req = urllib.request.Request(
        BRIDGE,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def dist(a, b):
    return ((a[0]-b[0])**2 + (a[1]-b[1])**2)**0.5

def angle_to(sx, sz, tx, tz):
    return math.atan2(tx-sx, -(tz-sz))

print("[recover] Starting recovery loop...")

for attempt in range(100):
    snap = call("snapshot")
    if not snap.get("ok"):
        time.sleep(0.5)
        continue
    
    info = snap.get("info", {})
    player = info.get("player", {})
    pos = info.get("player_pos", [0, 0])
    dead = player.get("dead", False)
    facing = player.get("facing", 0)
    
    if not dead:
        print(f"[recover] Player alive! hp={player.get('hp')} pos={pos}")
        break
    
    # Find spirit healer (The Pale Keeper)
    healer = None
    for e in info.get("nearby", []):
        if "Pale" in e.get("name", "") or "Keeper" in e.get("name", ""):
            healer = e
            break
    
    if not healer:
        print(f"[recover] No healer nearby, exploring...")
        call("explore")
        time.sleep(1)
        continue
    
    hx, hz = healer["x"], healer["z"]
    d = dist(pos, [hx, hz])
    print(f"[recover] Healer at [{hx},{hz}], dist={d:.1f}, facing={facing:.2f}")
    
    if d < 5:
        # Close enough - try to resurrect
        print("[recover] Close to healer, attempting resurrection...")
        call("step", {"action_id": 3})
        time.sleep(1)
    else:
        # Navigate toward healer using raw_move
        target_angle = angle_to(pos[0], pos[1], hx, hz)
        diff = (target_angle - facing + math.pi) % (2 * math.pi) - math.pi
        
        if abs(diff) > 0.3:
            # Turn toward healer
            call("raw_move", {"kind": "turnRight" if diff > 0 else "turnLeft"})
            time.sleep(0.2)
        else:
            # Move forward
            call("raw_move", {"kind": "forward"})
            time.sleep(0.2)

print("[recover] Recovery loop complete")
