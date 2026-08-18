import urllib.request, json, time
def post(payload):
    resp = urllib.request.urlopen("http://127.0.0.1:8791/", timeout=30,
                                  data=json.dumps(payload).encode()).read()
    return json.loads(resp)

print("start:", post({"action":"snapshot"})["info"].get("player_pos"))
# farm = idx 0
for i in range(5):
    r = post({"action":"step", "idx": 0})
    info = r.get("info", {})
    print(f"step(0)=farm {i}: pos={info.get('player_pos')} kills={info.get('kills')} "
          f"in_combat={info.get('in_combat')} hp={(info.get('player') or {}).get('hp')}")
    time.sleep(0.5)
