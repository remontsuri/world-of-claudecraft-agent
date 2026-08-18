"""
World of ClaudeCraft — self-improving llama agent (headless Sim).
Loop (GVU: Generate-Verify-Update, per arxiv 2512.02731):
  1. Play an episode using current strategy prompt.
  2. Summarize results (kills, deaths, xp, quests, errors) and ask llama to REFINE.
  3. Save refined strategy to strategy.json; next episode loads it. Repeat.

Obs layout (from python/README_agent.md + simple_warrior_agent.py, offsets resolved
dynamically because ability slots pad to largest kit):
  self        : 0..15   (0=hp_frac, 2=level/MAX, 9=dead, 10=in_combat, 11=auto_attack)
  abilities    : 16 .. 16+2*N   ([ready, cd_frac] per slot)
  target       : +9   (has, hpFrac, lvlDiff/5, dist/40, sin, cos, hostile, lootable, aggro)
  mobs         : +30  (5*6: dist/40, sin, cos, hpFrac, lvlDiff/5, aggro)
  interactable : +5   (has, dist/40, sin, cos, type)  .33=corpse .66=object 1=npc
  quests       : +2*Q

Key facts from headless/CLAUDE.md + README_agent.md:
  - target_nearest (8) only locks a HOSTILE within acquisition radius (~38yd =>
    dist/40 < 0.95). Movement provokes aggro; hostile then walks into melee.
  - interact (58) on NPC (type=1) accepts/turns in quests; on corpse (type=.33)
    loots it.
  - action 1=forward, 8=target_nearest, 9=attack, 10..57=abilities, 58=interact.

Usage:
  python llama_selfplay.py --episodes 5 --steps 300 --class warrior --seed 42
"""
import argparse, json, os, time
from wow_env import WoWClassicEnv

LLAMA_URL = "http://127.0.0.1:8081/v1/chat/completions"
STRATEGY_FILE = os.path.join(os.path.dirname(__file__), "strategy.json")

BASE_STRATEGY = """You play World of ClaudeCraft (WoW-like MMO) via discrete actions. You IMPROVE by playing.
Pick ONE action index each tick. ACTION space:
0:noop 1:forward 2:back 3:turn_left 4:turn_right 5:strafe_left 6:strafe_right
8:target_nearest 9:attack 10..57:abilities 58:interact 59:stop
OBJECTIVE: kill mobs, complete quests, gain XP, survive. Standing still = failure.
KEY FACTS (from game docs):
- mobs[].dist and target.dist are in WORLD UNITS (dist/40 in obs). A mob at dist/40=0.95 is ~38yd — target_nearest can lock it only when within that range.
- interactable.type: 0.33=corpse, 0.66=object, 1.0=quest NPC.
- target_nearest (8) only locks a HOSTILE within ~38yd. You must WALK (forward) to get mobs into range; movement provokes aggro and the mob then closes to melee on its own.
RULES:
- If a quest NPC is nearby (interactable.has and type==1.0 and dist<40): action 58:interact (accept/turn in quest). Repeat until quests_done increases.
- Else if a lootable corpse is nearby (interactable.has and type==0.33 and dist<5): action 58:interact to loot.
- Else if a mob with level_diff <= 0 (not stronger) exists:
  * If dist/40 > 0.95 (far): action 1:forward to approach. If off-heading (sin not ~0), turn (3/4) first.
  * If dist/40 <= 0.95: action 8:target_nearest, then 9:attack. Keep attacking (9) while in combat. Use abilities (10..57) when off cooldown.
- NEVER fight a mob with level_diff > 0. If such a mob attacks you, action 2:back to retreat.
- If hp_frac < 0.3 and in combat: action 2:back, stop attacking until safe.
- If no mob/NPC nearby: action 1:forward to explore (veer every ~15 steps with 3/4 to sweep).
- Avoid 0:noop unless literally nothing else applies."""


def chat(system, user, max_tokens=200, temperature=0.4):
    body = {"model": "local", "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], "temperature": temperature, "max_tokens": max_tokens}
    try:
        import subprocess
        out = subprocess.run(
            ["curl", "-s", "--max-time", "90", "-X", "POST", LLAMA_URL,
             "-H", "content-type: application/json",
             "-d", json.dumps(body)],
            capture_output=True, text=True, timeout=95)
        j = json.loads(out.stdout)
        return j["choices"][0]["message"]["content"] or ""
    except Exception as e:
        return f"ERR:{e}"


def parse_action(txt, n_actions):
    try:
        s = txt.find("{")
        e = txt.rfind("}")
        if s != -1 and e != -1:
            d = json.loads(txt[s:e+1])
            a = int(d.get("action", 0))
            if 0 <= a < n_actions:
                return a
    except Exception:
        pass
    import re
    m = re.search(r'"action"\s*:\s*(\d+)', txt)
    if m:
        a = int(m.group(1))
        if 0 <= a < n_actions:
            return a
    return 0


def resolve_offsets(action_names):
    n_abilities = sum(1 for a in action_names if a.startswith("ability_"))
    self_n = 16
    abilities_n = n_abilities * 2
    target_off = self_n + abilities_n
    mobs_off = target_off + 9
    interact_off = mobs_off + 5 * 6
    return {"self_n": self_n, "target_off": target_off, "mobs_off": mobs_off,
            "interact_off": interact_off}


def summarize_obs(obs, off):
    def f(i): return round(float(obs[i]), 3) if i < len(obs) else 0.0
    to = off["target_off"]
    mo = off["mobs_off"]
    io = off["interact_off"]
    mobs = []
    for i in range(5):
        b = mo + i * 6
        if b + 5 < len(obs) and obs[b] < 1.5:  # dist<60
            mobs.append({
                "dist": round(obs[b] * 40, 1),
                "hp_frac": f(b + 3),
                "level_diff": round(obs[b + 4] * 5, 1),
                "aggro": int(obs[b + 5] > 0.5),
            })
    itype = f(io + 4)
    return {
        "hp_frac": f(0),
        "level_norm": f(2),
        "dead": int(f(9) > 0.5),
        "in_combat": int(f(10) > 0.5),
        "auto_attack": int(f(11) > 0.5),
        "target": {"has": int(f(to) > 0.5), "hp_frac": f(to + 1),
                    "level_diff": round(f(to + 2) * 5, 1),
                    "dist": round(f(to + 3) * 40, 1),
                    "lootable": int(f(to + 7) > 0.5),
                    "aggro": int(f(to + 8) > 0.5)},
        "mobs": mobs,
        "interactable": {"has": int(f(io) > 0.5), "dist": round(f(io + 1) * 40, 1),
                          "type": round(itype, 2),
                          "type_name": ("npc" if abs(itype - 1.0) < 0.1
                                         else "corpse" if abs(itype - 0.33) < 0.1
                                         else "object" if abs(itype - 0.66) < 0.1
                                         else "none")},
        "quests_done": sum(1 for i in range(io + 5, len(obs), 2) if f(i) > 0.9),
        "quests_active": sum(1 for i in range(io + 5, len(obs), 2) if 0 < f(i) < 0.9),
    }


def play_episode(env, strategy, steps, episode_idx, off, names, n):
    obs, info = env.reset(seed=42 + episode_idx * 7)
    traj = []
    total_r = 0.0
    kills = deaths = quests = 0
    level_at_start = info.get("level", 1)
    interact_streak = 0
    steps_since_veer = 0
    veer_dir = 1
    for step in range(steps):
        summ = summarize_obs(obs, off)
        it = summ["interactable"]
        tgt = summ["target"]
        # interact only when essentially adjacent (5yd range per obs.ts encodeObs)
        # and capped at 2 consecutive steps so we never freeze on an NPC
        can_interact = (
            it["has"] and it["type_name"] in ("npc", "corpse")
            and it["dist"] < 5
            and interact_streak < 2
        )
        if can_interact:
            act = 58
            interact_streak += 1
        else:
            interact_streak = 0
            if tgt["has"] and tgt["dist"] <= 6:
                used_ability = False
                for slot in range(3):
                    if obs[16 + slot * 2] > 0.5:
                        act = 10 + slot
                        used_ability = True
                        break
                if not used_ability:
                    act = 9
            elif tgt["has"] and tgt["dist"] <= 38:
                act = 1
            elif any(m["level_diff"] <= 0 and m["dist"] <= 38 for m in summ["mobs"]):
                act = 8
            else:
                # explore: forward + zigzag every ~15 steps (per simple_warrior_agent)
                steps_since_veer += 1
                if steps_since_veer >= 15:
                    veer_dir *= -1
                    steps_since_veer = 0
                act = 1 if veer_dir > 0 else 4
        try:
            obs, reward, terminated, truncated, info = env.step(act)
        except Exception:
            obs, info = env.reset(seed=42 + episode_idx * 7 + step)
            terminated = truncated = False
        total_r += reward
        kills = info.get("kills", kills)
        deaths = info.get("deaths", deaths)
        quests = info.get("quests_done", quests)
        traj.append((act, reward, info.get("hp", 0), info.get("level", 1)))
        if terminated or truncated:
            obs, info = env.reset(seed=42 + episode_idx * 7 + step)
    return {
        "episode": episode_idx, "steps": steps, "total_reward": round(total_r, 1),
        "kills": kills, "deaths": deaths, "quests_done": quests,
        "level_start": level_at_start, "level_end": info.get("level", level_at_start),
        "traj": traj[-20:],  # last 20 steps for reflection context
    }


def reflect(strategy, results):
    summary = json.dumps(results, indent=1)
    user = (
        f"CURRENT STRATEGY:\n{strategy}\n\n"
        f"EPISODE RESULTS:\n{summary}\n\n"
        f"You just played with that strategy. Analyze what went wrong "
        f"(e.g. died too much, fought too-strong mobs, did not loot/quest, ran away, "
        f"failed to approach mobs). Write an IMPROVED strategy (concise, actionable rules) "
        f"that fixes those mistakes. Reply with ONLY the new strategy text, no preamble."
    )
    new = chat("You are a self-improving game agent. Refine your own strategy from results.",
               user, max_tokens=700, temperature=0.5)
    if new.startswith("ERR"):
        return strategy
    return new.strip()


def load_strategy():
    if os.path.exists(STRATEGY_FILE):
        try:
            with open(STRATEGY_FILE) as fh:
                return fh.read().strip()
        except Exception:
            pass
    return BASE_STRATEGY


def save_strategy(s):
    with open(STRATEGY_FILE, "w") as fh:
        fh.write(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=4)
    ap.add_argument("--steps", type=int, default=250)
    ap.add_argument("--class", dest="pclass", default="warrior")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reset-strategy", action="store_true",
                    help="ignore saved strategy.json and start from BASE_STRATEGY")
    args = ap.parse_args()

    time.sleep(2)
    env = WoWClassicEnv(player_class=args.pclass)
    off = resolve_offsets(env.action_names)
    names = env.action_names
    n = len(names)
    strategy = BASE_STRATEGY if args.reset_strategy else load_strategy()
    print(f"Loaded strategy (len={len(strategy)}); obs_off={off}", flush=True)
    all_results = []
    for ep in range(args.episodes):
        print(f"\n=== EPISODE {ep+1}/{args.episodes} ===", flush=True)
        res = play_episode(env, strategy, args.steps, ep, off, names, n)
        all_results.append(res)
        print(f"[ep{ep+1}] reward={res['total_reward']} kills={res['kills']} "
              f"deaths={res['deaths']} quests={res['quests_done']} "
              f"lvl {res['level_start']}->{res['level_end']}", flush=True)
        strategy = reflect(strategy, all_results)
        save_strategy(strategy)  # persist so next run continues improving
        print(f"[ep{ep+1}] strategy refined (len={len(strategy)})", flush=True)
    env.close()
    print("\n=== FINAL STRATEGY ===\n", strategy, flush=True)


if __name__ == "__main__":
    main()
