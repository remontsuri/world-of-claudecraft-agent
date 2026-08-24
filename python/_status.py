import json, urllib.request, sys
BRIDGE = "http://127.0.0.1:8791/"
def post(p, timeout=30):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(BRIDGE, data=json.dumps(p).encode(), headers={"Content-Type":"application/json"}), timeout=timeout)
        return json.load(raw)
    except Exception as e:
        return {"_err": repr(e)}
h = post({"action":"snapshot"}, 10)
info = h.get("info", {})
p = info.get("player", {}) or {}
print("health_ok=", h.get("ok"))
print("dead=", p.get("dead"), "hp=", p.get("hp"), "maxHp=", p.get("maxHp"), "level=", p.get("level"))
print("player_pos=", info.get("player_pos"))
