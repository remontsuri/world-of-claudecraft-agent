import urllib.request, json
def post(payload):
    resp = urllib.request.urlopen("http://127.0.0.1:8791/", timeout=30,
                                  data=json.dumps(payload).encode()).read()
    return json.loads(resp).get("info", {})

print("start:", post({"action":"snapshot"}).get("player_pos"))
for i in range(5):
    info = post({"action":"raw_move", "kind":"forward"})
    print(f"forward {i}: pos={info.get('player_pos')}")
for i in range(3):
    info = post({"action":"raw_move", "kind":"turnLeft"})
    print(f"turnLeft {i}: pos={info.get('player_pos')}")
# try navigate to a far point
info = post({"action":"navigate", "x": 50, "z": 50, "max_steps": 60})
print("navigate(50,50):", info.get("player_pos"), "nearby npc:",
      [e.get('kind') for e in (info.get('nearby') or []) if e.get('kind')=='npc'])
