"""Headless nav training: teach the agent to walk TO a point.

Reward = distance reduction per step. This trains the low-level
turn/forward policy that the live agent's navigateToCoord does by script —
the exact skill that fails at fences. Deterministic sim, seed fixed.
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quick_headless_train import HeadlessEnv

def main(episodes=8, steps_per=250):
    q = {}
    rng = random.Random(3)
    alpha, gamma = 0.3, 0.92
    targets = [(20, 20), (-15, 25), (30, -10), (-25, -20)]
    history = []
    for ep in range(episodes):
        tx, tz = targets[ep % len(targets)]
        env = HeadlessEnv(seed=42)
        obs = env.obs
        info = {}
        prev_d = None
        ep_prog = []
        # state: дискретизация угла к цели (8 секторов) + дистанция (близко/средне/далеко)
        def state_of():
            px, pz = info.get("px", 0), info.get("pz", 0)
            dx, dz = tx - px, tz - pz
            d = (dx*dx + dz*dz) ** 0.5
            ang = math.atan2(dx, dz)          # желаемый курс
            rel = ((ang - (info.get("facing") or 0) + 3.14159) % 6.28318) - 3.14159
            sector = int((rel + 3.14159) / (6.28318 / 8)) % 8   # 0..7 куда повернуть
            band = 0 if d < 5 else (1 if d < 15 else 2)
            return f"sec={sector}|d={band}", d, sector
        s, d, _ = state_of()
        for t in range(steps_per):
            _, d, sec = state_of()
            # действия: 3=поворот влево, 4=вправо, 1=вперёд, 7=прыжок(заборы)
            cands = [3, 4, 1, 7]
            if rng.random() < 0.15:
                a = rng.choice(cands)
            else:
                a = max(cands, key=lambda c: q.get((s, c), 0.0))
            obs, r, term, trunc, info = env.step(a)
            s2, d2, _ = state_of()
            reward = (prev_d - d2) if prev_d is not None else 0.0   # прогресс
            prev_d = d2
            old = q.get((s, a), 0.0)
            best_next = max((q.get((s2, c), 0.0) for c in cands), default=0.0)
            q[(s, a)] = old + 0.3 * (reward + gamma * best_next - old)
            s = s2
            ep_prog.append(round(d,1))
            if d < 4:
                print(f"  ep{ep}: REACHED target at t={t}!"); break
        moved = sum(1 for i in range(1,len(ep_prog)) if abs(ep_prog[i]-ep_prog[i-1])>0.05)
        history.append((ep, ep_prog[-1] if ep_prog else None, moved))
        print(f"ep{ep}: dist {tx,tz} final={ep_prog[-1] if ep_prog else '?'} "
              f"moving_steps={moved}/{len(ep_prog)}")
        env.close()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
              "experience_nav.json"), "w", encoding="utf-8") as f:
        json.dump({"trained_at": time.time(), "q": [[list(k),v] for k,v in q.items()]},
                  f, ensure_ascii=False)
    print("saved experience_nav.json")

import math
main()
