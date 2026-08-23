"""Quick offline training: tabular Q-learning against the HEADLESS env server.

Deterministic sim (seed fixed), no network, no browser — episodes are cheap and
reproducible. Trains the same (bucket, action) key shape as the live agent's
ExperienceStore so weights can be merged back.

Usage: python quick_headless_train.py [episodes] [--out FILE]
"""
import json
import math
import os
import random
import subprocess
import sys
import threading
import queue
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "dist-env", "env_server.cjs")

ACTIONS = 61          # obs.ts action space (B1 format)
EPISODE_STEPS = 400


class HeadlessEnv:
    """NDJSON client over env_server.cjs stdin/stdout."""

    def __init__(self, player_class="mage", seed=42):
        self.proc = subprocess.Popen(
            ["node", SERVER],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, cwd=HERE + "/..",
            bufsize=1)
        self._q = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        resp = self._send({"cmd": "reset", "player_class": player_class,
                           "seed": seed})
        self.obs = resp["obs"]

    def _pump(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line.startswith("{"):
                try:
                    self._q.put(json.loads(line))
                except Exception:
                    pass

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()
        return self._q.get(timeout=30)

    def step(self, action: int):
        resp = self._send({"cmd": "step", "action": int(action)})
        return (resp.get("obs"), resp.get("reward", 0.0),
                resp.get("terminated", False), resp.get("truncated", False),
                resp.get("info") or {})

    def close(self):
        try:
            self._send({"cmd": "close"})
        except Exception:
            pass
        self.proc.terminate()


def bucket(obs):
    """Coarse key from the obs vector: hp_frac, in_combat, nearby count."""
    hp = round(obs[2], 1) if len(obs) > 2 else 1.0
    combat = 1 if (len(obs) > 4 and obs[4] != 0) else 0
    mobs = min(10, sum(1 for i in range(16, 96, 3)
                       if i < len(obs) and obs[i] != 0))
    return f"hl|hp={hp}|cb={combat}|mobs={mobs}"


def main():
    episodes = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    out_path = os.path.join(HERE, "experience_headless.json")
    q = {}
    counts = {}
    rng = random.Random(7)
    alpha, gamma = 0.25, 0.95
    eps_start, eps_end = 0.35, 0.05

    total_rewards = []
    for ep in range(episodes):
        env = HeadlessEnv(seed=42 + ep)
        obs = env.obs
        s = bucket(obs)
        ep_r, kills0, deaths0 = 0.0, None, None
        best_q = None
        for t in range(EPISODE_STEPS):
            # epsilon-greedy over a small action subset (movement/attack/heal-ish)
            # combat cycle: target -> approach -> attack; every 3rd step add abilities
            subset = [8, 9, 1, 3, 4] if t % 4 else [8, 9, 10, 11, 12]
            if rng.random() < max(eps_end, eps_start - ep * 0.05):
                a = rng.choice(subset)
            else:
                vals = {cand: q.get((s, cand), 0.0) for cand in subset}
                a = max(vals, key=vals.get)
            obs2, r, term, trunc, info = env.step(a)
            s2 = bucket(obs2)
            old = q.get((s, a), 0.0)
            best_next = max((q.get((s2, c), 0.0) for c in subset), default=0.0)
            q[(s, a)] = old + alpha * (r + gamma * best_next - old)
            s = s2
            ep_r += r
            if term or trunc:
                break
        total_rewards.append(ep_r)
        print(f"ep{ep}: reward={ep_r:+.1f} steps={t+1} Q-keys={len(q)}")
        env.close()

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"trained_at": time.time(), "episodes": episodes,
                   "q": [[list(k), v] for k, v in q.items()]},
                  f, ensure_ascii=False)
    print(f"\navg reward last 3: {sum(total_rewards[-3:])/3:+.1f}")
    print(f"saved: {out_path}")


if __name__ == "__main__":
    main()
