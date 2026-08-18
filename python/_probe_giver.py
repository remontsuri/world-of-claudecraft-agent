import urllib.request, json, time
def snap():
    resp = urllib.request.urlopen("http://127.0.0.1:8791/", timeout=30,
                                  data=json.dumps({"action": "snapshot"}).encode()).read()
    return json.loads(resp).get("info", {})
def post(payload):
    resp = urllib.request.urlopen("http://127.0.0.1:8791/", timeout=30,
                                  data=json.dumps(payload).encode()).read()
    return json.loads(resp).get("info", {})

info = snap()
print("after reset/prime: quests.active =", info.get("quests", {}).get("active"))
print("nearby kinds:", [(e.get("kind"), e.get("type"), e.get("questIds") or e.get("questId"))
                         for e in (info.get("nearby") or [])])

# try to find a quest giver by exploring
found = None
for i in range(15):
    info = post({"action": "explore", "steps": 30})
    near = info.get("nearby") or []
    g = [e for e in near if (e.get("kind") == "npc" or e.get("type") == "npc")
         and (e.get("questIds") or e.get("questId"))]
    if g:
        found = g[0]
        print(f"[explore {i}] FOUND giver: {g[0]}")
        break
    pkinds = [(e.get("kind"), e.get("type")) for e in near]
    print(f"[explore {i}] nearby={pkinds} pos={info.get('player_pos')}")
    time.sleep(0.3)

if found:
    print("GIVER coords:", found.get("x"), found.get("z"), "questIds:", found.get("questIds"))
else:
    print("NO giver found after 15 explore bursts")
