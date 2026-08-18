"""_probe_mobs.py — find where mobs are and how far explore moves us."""
import math, time
from browser_env import BrowserEnv

env = BrowserEnv(player_class="warrior", max_steps=100000, seed=3)
env.reset(seed=3)

def mobs_of(info):
    return [e for e in (info.get("nearby") or [])
            if (e.get("kind")=="mob" or e.get("type")=="mob") and not e.get("lootable") and not e.get("dead")]

info = env._last_info
print(f"[start] pos={info.get('player_pos')} mobs={len(mobs_of(info))} nearby={len(info.get('nearby') or [])}")
for i in range(20):
    env.explore_walk(steps=15)
    info = env._last_info
    m = mobs_of(info)
    pos = info.get("player_pos")
    print(f"[{i:2d}] pos={pos} mobs={len(m)} nearby_types={sorted({e.get('kind') or e.get('type') for e in (info.get('nearby') or [])})}")
    if m:
        md = min(math.hypot(e.get('x',0)-pos[0], e.get('z',0)-pos[1]) for e in m)
        print(f"      nearest mob dist={md:.1f}")
        break
time.sleep(0.2)
