import urllib.request, json, time
def post(payload):
    resp = urllib.request.urlopen("http://127.0.0.1:8791/", timeout=30,
                                  data=json.dumps(payload).encode()).read()
    return json.loads(resp)

r = post({"action":"respawn"})
info = r.get("info", {})
print("after respawn: dead=", (info.get("player") or {}).get("dead"),
      "hp=", (info.get("player") or {}).get("hp"),
      "pos=", info.get("player_pos"))
time.sleep(1)
# try moving after respawn
for i in range(3):
    info = post({"action":"raw_move", "kind":"forward"}).get("info", {})
    print(f"forward {i}: pos={info.get('player_pos')} hp={(info.get('player') or {}).get('hp')}")
