import urllib.request, json
resp = urllib.request.urlopen("http://127.0.0.1:8791/", timeout=30,
                              data=json.dumps({"action": "snapshot"}).encode()).read()
info = json.loads(resp).get("info", {})
print("KEYS:", list(info.keys()))
print("player:", json.dumps(info.get("player", {}), ensure_ascii=False)[:400])
print("quests:", json.dumps(info.get("quests", {}), ensure_ascii=False)[:600])
print("nearby count:", len(info.get("nearby") or []))
for e in (info.get("nearby") or [])[:10]:
    print("  ent:", e.get("kind"), e.get("type"), "name=", e.get("name"),
          "qids=", e.get("questIds") or e.get("questId"),
          "x=", e.get("x"), "z=", e.get("z"))
print("player_pos:", info.get("player_pos"))
