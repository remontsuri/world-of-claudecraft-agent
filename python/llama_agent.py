"""
World of ClaudeCraft — local-llama self-play agent (headless Sim).
Reads obs -> asks local llama (http://localhost:8081/v1) -> picks action -> gets reward.
Self-improves by feeding its own recent (obs,action,reward) history back as context.

Usage:
  python python/llama_agent.py --steps 2000 --class warrior
"""
import argparse, json, time, subprocess, sys, urllib.request
from wow_env import WoWClassicEnv

LLAMA_URL = "http://localhost:8081/v1/chat/completions"

SYS = """You play World of ClaudeCraft (WoW-like MMO) via a discrete action space.
You receive the current observation and must pick ONE action index.
Respond with ONLY JSON: {"action": <int>, "reason": "<short>"}
Priority heuristic to follow unless observation clearly says otherwise:
1. If target hostile and in range -> action "attack" (index from action_names).
2. If not in combat and a mob is near -> "target_nearest" then move "forward" toward it.
3. If hp low and fleeing possible -> "back"/"strafe" away.
4. Use abilities when off cooldown to maximize damage.
Prefer staying alive (avoid deaths) and killing mobs (reward)."""

def ask_llama(action_names, obs_summary, history, max_tokens=400):
    names = ", ".join(f"{i}:{n}" for i, n in enumerate(action_names))
    hist = "\n".join(history[-6:]) if history else "(none)"
    user = (
        f"ACTION_NAMES: {names}\n"
        f"OBS_SUMMARY: {obs_summary}\n"
        f"RECENT HISTORY (action->reward):\n{hist}\n"
        f"Pick the best action index now."
    )
    body = {
        "model": "local",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }
    try:
        req = urllib.request.Request(LLAMA_URL, data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.load(r)
        txt = j["choices"][0]["message"]["content"] or ""
        m = txt.find("{")
        e = txt.rfind("}")
        if m != -1 and e != -1:
            d = json.loads(txt[m:e+1])
            return int(d.get("action", 0)), d.get("reason", "")
    except Exception as e:
        return 0, f"err:{e}"
    return 0, "fallback"


def summarize_obs(obs, action_names):
    # obs is a 567-float vector. We cannot send all; extract compact signals.
    # Per skill doc offsets are class-specific; we surface raw few + let llama pick.
    # Keep it simple: report first self block (0..15) + target sign + nearest mob flag.
    def f(i): return round(float(obs[i]), 3) if i < len(obs) else 0.0
    return {
        "self_hp_frac": f(2),          # approx hp/maxHp if normalized
        "self_x": f(0), "self_y": f(1),
        "target_has": f(9),
        "in_combat": f(7),
        "nearest_mob_dist_norm": f(30) if len(obs) > 30 else 0.0,
        "note": "see ACTION_NAMES; 0=noop,1=forward,2=back,3=turn_left,4=turn_right,8=target_nearest,9=attack,10+=abilities,59=stop"
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--class", dest="pclass", default="warrior")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    time.sleep(2)  # let env server boot
    env = WoWClassicEnv(player_class=args.pclass)
    obs, info = env.reset(seed=args.seed)
    action_names = env.action_names
    print(f"[init] obs={obs.shape} actions={len(action_names)} seed={args.seed}", flush=True)

    history = []
    total_reward = 0.0
    kills = 0
    deaths = 0
    t0 = time.time()
    for step in range(args.steps):
        summ = summarize_obs(obs, action_names)
        act, reason = ask_llama(action_names, summ, history)
        if act < 0 or act >= len(action_names):
            act = 0
        obs, reward, terminated, truncated, info = env.step(act)
        total_reward += reward
        kills = info.get("kills", kills)
        deaths = info.get("deaths", deaths)
        history.append(f"step{step}: act={act}({action_names[act]}) r={reward:.2f} hp={info.get('hp')} lvl={info.get('level')}")
        if step % 50 == 0:
            print(f"[t{step}] act={action_names[act]} r={reward:.2f} tot={total_reward:.1f} "
                  f"kills={kills} deaths={deaths} hp={info.get('hp')} lvl={info.get('level')} "
                  f"({reason})", flush=True)
        if terminated or truncated:
            print(f"[episode end] step={step} tot_reward={total_reward:.1f} kills={kills} deaths={deaths}", flush=True)
            obs, info = env.reset(seed=args.seed + step)
    dt = time.time() - t0
    print(f"[done] steps={args.steps} reward={total_reward:.1f} kills={kills} deaths={deaths} "
          f"time={dt:.1f}s ({args.steps/dt:.1f} step/s)", flush=True)
    env.close()


if __name__ == "__main__":
    main()
