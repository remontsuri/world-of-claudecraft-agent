"""play_autonomous.py — persistent autonomous game session (Level 3).

NOT a diagnostic benchmark. This is the real target: an agent that observes the
online WoC world, chooses its OWN goals/actions from learned policy + exploration,
acts, gets consequences, remembers, and keeps playing — without any
`if quest: farm()` / `if far: return()` script steering it.

Design:
- reset -> observe -> decide -> act -> observe -> learn -> repeat, for N steps.
- NO forcing functions (no force_far / force_to_band). The agent walks where it
  decides. We just feed it the world.
- Memory persists every SAVE_EVERY steps (survives crashes / restarts).
- Metrics track BEHAVIOUR DEVELOPMENT, not P(return):
    steps, kills, quests_accepted, quests_done, deaths, xp, copper,
    unique_npcs, unique_areas (by position cell), exploration_cells,
    repeated_mistakes (same bad action in same bucket 2x+), recovery
    (after a negative lesson, a different action chosen next).
- One-line-per-step log to autonomous_log.jsonl (append), periodic summary to
  stdout. No chat spam.

No reward change. No Sim change. No PPO. Policy already chooses; this just lets
it live.
"""

import json
import os
import sys
import time
from collections import Counter, defaultdict

from browser_env import BrowserEnv
from agent import Agent
from memory import ExperienceStore, _bucket
from world_state import build_world_state

EXP_PATH = os.path.join(os.path.dirname(__file__), "experience_autonomous.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "autonomous_log.jsonl")
N_STEPS = int(os.environ.get("AUTONOMOUS_STEPS", "3000"))
SAVE_EVERY = int(os.environ.get("SAVE_EVERY", "200"))
WINDOW = int(os.environ.get("AUTONOMOUS_WINDOW", "500"))  # Level-4 windowed metrics
SEED = int(os.environ.get("AUTONOMOUS_SEED", "4242"))


def cell_of(pos, size=20.0):
    """Coarse position cell for exploration tracking."""
    if not pos:
        return "none"
    return f"{int(pos[0]//size)}_{int(pos[1]//size)}"


def main():
    if os.path.exists(EXP_PATH):
        # resume: keep learned memory across runs
        print(f"[autonomous] resuming from {EXP_PATH}")
    mem = ExperienceStore(path=EXP_PATH)
    env = BrowserEnv(player_class="warrior", max_steps=100000, seed=SEED)
    env.reset(seed=SEED)
    agent = Agent(env, mem, seed=SEED * 3 + 7)

    # metrics
    m = {
    "steps": 0, "kills": 0, "quests_accepted": 0, "quests_done": 0,
    "deaths": 0, "xp": 0, "copper": 0,
    "unique_npcs": set(), "explored_cells": set(),
    "action_counts": Counter(), "env_errors": 0,
    "neg_lessons": 0, "recovery_after_neg": 0,
    "repeated_mistakes": 0,
    "win_reward": 0.0, "win_deaths": 0, "win_repeat": 0,
    "win_actions": Counter(), "win_steps": 0, "deaths_prev": 0,
    }
    # track per-bucket last action + whether it was negative, to measure recovery
    last_bucket_action = {}
    last_bucket_neg = {}
    # (bucket, action) pairs that already yielded a negative lesson — used to
    # detect REPEATED mistakes (same bad action chosen again in the same bucket).
    neg_state_action = set()

    logf = open(LOG_PATH, "a", encoding="utf-8")

    def snap(info):
        ws = build_world_state(info)
        return ws

    prev = snap(env._last_info)
    start = time.time()

    for i in range(N_STEPS):
        try:
            rec = agent.step()
        except Exception:
            m["env_errors"] += 1
            # restart a fresh env if the server died
            try:
                env.close()
            except Exception:
                pass
            env = BrowserEnv(player_class="warrior", max_steps=100000, seed=SEED + i)
            env.reset(seed=SEED + i)
            agent = Agent(env, mem, seed=SEED * 3 + 7 + i)
            rec = {"action": "RESTART", "verdict": "ENV_ERROR", "outcome_kind": "ENV_ERROR",
                   "reward": 0.0, "ws_before": prev, "ws_after": snap(env._last_info)}

        # respawn glue: if the character died, release spirit + revive so the
        # loop keeps collecting honest signal (does NOT mutate the model)
        if rec["ws_after"].get("hp_frac", 1.0) <= 0.0 or rec.get("ws_after", {}).get("deaths", 0) > m["deaths"]:
            env.respawn()
            rec["ws_after"] = snap(env._last_info)

        ws = rec["ws_after"]
        info = env._last_info
        a = rec["action"]
        m["steps"] += 1
        m["action_counts"][a] += 1
        m["xp"] = ws.get("xp", m["xp"])
        m["copper"] = ws.get("copper", m["copper"])
        m["deaths"] = ws.get("deaths", m["deaths"])
        m["kills"] = ws.get("kills", m["kills"])
        # quests
        active = info.get("quests", {}).get("active") or []
        done = info.get("quests", {}).get("done") or []
        m["quests_accepted"] = max(m["quests_accepted"], len(active) + len(done))
        m["quests_done"] = max(m["quests_done"], len(done))
        # exploration
        cell = cell_of(info.get("player_pos"))
        m["explored_cells"].add(cell)
        for e in (info.get("nearby") or []):
            if e.get("kind") == "npc":
                m["unique_npcs"].add(e.get("id") or e.get("name") or str(e.get("x"))+","+str(e.get("z")))
        # --- long-horizon learning telemetry (user audit 2026-08-18) ---
        # Measure the ACTUAL causal chain, not just "got a negative reward":
        #   negative experience -> same/similar state -> SAME action (repeated_mistake)
        #                          -> DIFFERENT action (recovery)
        # Uses the exact bucket key the policy reads (memory._bucket over the
        # shared WorldState). Previously `bucket` was hardcoded to None, so these
        # metrics were never computed and neg_lessons could NOT prove learning.
        bucket = None
        bucket_after = None
        neg = rec["reward"] < -0.1
        was_repeat = False
        if rec["outcome_kind"] != "ENV_ERROR":
            bucket = _bucket(rec["ws_before"])
            bucket_after = _bucket(rec["ws_after"])
        if neg:
            m["neg_lessons"] += 1
        if bucket is not None:
            prev_act = last_bucket_action.get(bucket)
            prev_neg = last_bucket_neg.get(bucket, False)
            # recovery: previous step in THIS bucket was negative, now a
            # DIFFERENT action chosen -> behaviour adapted to experience.
            if prev_neg and prev_act is not None and prev_act != a:
                m["recovery_after_neg"] += 1
            # repeated mistake: this (bucket, action) already produced a negative
            # lesson before, and we chose it AGAIN in the same bucket.
            if (bucket, a) in neg_state_action:
                m["repeated_mistakes"] += 1
                was_repeat = True
            if neg:
                neg_state_action.add((bucket, a))
            last_bucket_action[bucket] = a
            last_bucket_neg[bucket] = neg
        # windowed Level-4 metrics (trend across windows of WINDOW steps)
        m["win_reward"] += rec["reward"]
        m["win_steps"] += 1
        m["win_actions"][a] += 1
        dnew = ws.get("deaths", 0)
        if dnew > m["deaths_prev"]:
            m["win_deaths"] += (dnew - m["deaths_prev"])
            m["deaths_prev"] = dnew
        if was_repeat:
            m["win_repeat"] += 1
        # log one line
        row = {
            "step": i, "t": round(time.time() - start, 1),
            "action": a, "verdict": rec["verdict"], "kind": rec["outcome_kind"],
            "reward": round(rec["reward"], 3),
            "bucket_before": bucket, "bucket_after": bucket_after,
            "hp": round(ws.get("hp_frac", 0), 2),
            "quest_status": ws.get("quest_status"),
            "dist": round(ws.get("distance_to_giver", 0), 1),
            "kills": ws.get("kills"), "xp": ws.get("xp"),
            "qprog": ws.get("quest_progress"), "cell": cell,
            "deaths": ws.get("deaths"),
        }
        logf.write(json.dumps(row, ensure_ascii=False) + "\n")
        if i % SAVE_EVERY == 0:
            mem.save()
            _summary(m, i, start, logf)
        if (i + 1) % WINDOW == 0:
            _window_summary(m, i, logf)
            m["win_reward"] = 0.0
            m["win_deaths"] = 0
            m["win_repeat"] = 0
            m["win_actions"] = Counter()
            m["win_steps"] = 0

    mem.save()
    logf.close()
    env.close()
    _summary(m, m["steps"], start, None, final=True)
    print(f"\n[autonomous] done. log -> {LOG_PATH}, memory -> {EXP_PATH}")


def _summary(m, i, start, logf, final=False):
    el = time.time() - start
    msg = (f"\n=== {'FINAL' if final else f'step {i}'} autonomous summary "
           f"(t={el:.0f}s, {m['steps']} steps) ===\n"
           f"  kills={m['kills']} quests_accepted={m['quests_accepted']} "
           f"quests_done={m['quests_done']} deaths={m['deaths']}\n"
           f"  xp={m['xp']} copper={m['copper']} explored_cells={len(m['explored_cells'])} "
           f"unique_npcs={len(m['unique_npcs'])} env_errors={m['env_errors']}\n"
           f"  actions={dict(m['action_counts'])}\n"
           f"  neg_lessons={m['neg_lessons']} repeated_mistakes={m['repeated_mistakes']} "
           f"recovery_after_neg={m['recovery_after_neg']}\n")
    print(msg)
    if logf is not None:
        logf.write(msg + "\n")
    if final:
        _window_summary(m, i, logf)


def _window_summary(m, i, logf):
    ws_ = m["win_steps"] or 1
    dist = {k: f"{v/ws_*100:.1f}%" for k, v in m["win_actions"].items()}
    msg = (f"\n--- window ending step {i} (last {m['win_steps']} steps) ---\n"
           f"  reward/100steps = {m['win_reward']/ws_*100:.2f}\n"
           f"  death/100steps  = {m['win_deaths']/ws_*100:.2f}\n"
           f"  repeated_error_rate = {m['win_repeat']/ws_*100:.2f}%\n"
           f"  action_dist = {dist}\n")
    print(msg)
    if logf is not None:
        logf.write(msg + "\n")


if __name__ == "__main__":
    sys.exit(main())
