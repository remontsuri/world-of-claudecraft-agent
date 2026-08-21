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
import atexit
import traceback
from collections import Counter, defaultdict

from browser_env import BrowserEnv, BrowserBridgeError
from agent import Agent
from memory import ExperienceStore, _bucket, WorldMemory
from world_state import build_world_state

EXP_PATH = os.path.join(os.path.dirname(__file__), "experience_autonomous.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "autonomous_log.jsonl")
LOCK_PATH = os.path.join(os.path.dirname(__file__), "play_autonomous.lock")
N_STEPS = int(os.environ.get("AUTONOMOUS_STEPS", "3000"))
SAVE_EVERY = int(os.environ.get("SAVE_EVERY", "200"))
WINDOW = int(os.environ.get("AUTONOMOUS_WINDOW", "500"))  # Level-4 windowed metrics
# Frozen-eval cadence: every MEASURE_EVERY steps, run a MEASUREMENT step
# (exploration_weight=0 -> no exploration bonus, learn=False -> no weight update).
# This measures the CURRENT policy's choice probabilities without contaminating
# them, so BEFORE/AFTER comparisons are valid (user audit 2026-08-20: the
# exploration_weight=0 path existed in agent.step_no_learn but was never called).
MEASURE_EVERY = int(os.environ.get("MEASURE_EVERY", "0"))  # 0 = disabled
SEED = int(os.environ.get("AUTONOMOUS_SEED", "4242"))


def _acquire_lock():
    """Ensure only ONE play_autonomous drives the character at a time.

    The terminal(background) harness sometimes spawns two python processes for a
    single launch; both would drive the SAME character through the same bridge and
    corrupt the shared experience_autonomous.json / log. Refuse to start if a live
    instance holds the lock; clear a stale lock whose PID is no longer running."""
    import ctypes
    pid = os.getpid()
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH) as f:
                old = int(f.read().strip())
        except (ValueError, OSError):
            old = None
        if old is not None:
            alive = False
            try:
                kernel32 = ctypes.windll.kernel32
                # PROCESS_QUERY_INFORMATION = 0x400
                handle = kernel32.OpenProcess(0x400, False, old)
                if handle:
                    # WAIT_OBJECT_0 (0) = exited, WAIT_TIMEOUT (258) = still alive
                    alive = kernel32.WaitForSingleObject(handle, 0) == 258
                    kernel32.CloseHandle(handle)
            except Exception:
                alive = False
            if alive:
                sys.stderr.write(
                    f"[autonomous] refusing to start: another instance (PID {old}) is alive (lock {LOCK_PATH})\n")
                sys.exit(2)
            try:
                os.remove(LOCK_PATH)
            except OSError:
                pass
    with open(LOCK_PATH, "w") as f:
        f.write(str(pid))
    return pid


def _release_lock():
    """Best-effort removal of the single-instance lock. Registered via atexit so
    it runs on ANY process exit (normal, uncaught exception, sys.exit). Without
    this a dead agent (e.g. bridge down -> sys.exit(3)) leaves a stale lock whose
    PID is no longer alive, and the launcher would see a 'live' PID and skip the
    restart — the agent would never come back until someone deletes the lock."""
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except OSError:
        pass


def cell_of(pos, size=20.0):
    """Coarse position cell for exploration tracking."""
    if not pos:
        return "none"
    return f"{int(pos[0]//size)}_{int(pos[1]//size)}"


def main():
    # --- crash telemetry: on ANY uncaught exception, write the FULL traceback to
    # agent_crash.log (not just the live terminal, which the launcher hides in a
    # /min window). This is what makes a silent agent death debuggable. ---
    import traceback as _tb
    _crash_path = os.path.join(os.path.dirname(__file__), "agent_crash.log")
    def _excepthook(etype, evalue, etb):
        try:
            with open(_crash_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== AGENT CRASH {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                _tb.print_exception(etype, evalue, etb, file=f)
        except OSError:
            pass
        # also echo to stderr so the launcher log captures it
        _tb.print_exception(etype, evalue, etb)
    sys.excepthook = _excepthook
    try:
        import faulthandler as _fh
        _fh.dump_traceback_later(15, exit=True, file=open(_crash_path, "a", encoding="utf-8"))
    except Exception:
        pass

    _acquire_lock()  # refuse to run if another instance already drives the char
    # Release the single-instance lock on ANY exit (normal, exception, sys.exit),
    # so a dead agent (e.g. bridge down -> sys.exit(3)) never leaves a stale
    # lock with a dead PID that fools the launcher into thinking it is alive and
    # skipping the restart. atexit fires even on sys.exit().
    atexit.register(_release_lock)
    # Record our live PID so the launcher's singleton check (agent.pid) tracks
    # the real long-lived process. (Previously the launcher wrote this via a
    # python -c wrapper; now the module records it directly and reliably.)
    try:
        with open(os.path.join(os.path.dirname(__file__), "agent.pid"), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    if os.path.exists(EXP_PATH):
        # resume: keep learned memory across runs
        print(f"[autonomous] resuming from {EXP_PATH}")
    mem = ExperienceStore(path=EXP_PATH)
    try:
        env = BrowserEnv(player_class="warrior", max_steps=100000, seed=SEED)
        env.reset(seed=SEED)
    except Exception as e:
        # The bridge is down (CDP/HTTP transport rejected) or the game tab is
        # not ready. Previously this threw at import time with __file__ undefined
        # (launcher used exec(open().read())) and died silently with an empty
        # agent_run.log. Now we log it honestly and exit so the launcher's 10s
        # loop restarts us cleanly once the bridge is up.
        sys.stderr.write(
            f"[autonomous] FATAL: cannot init BrowserEnv (bridge up? game tab ready?): {type(e).__name__}: {e}\n"
        )
        sys.exit(3)
    agent = Agent(env, mem, seed=SEED * 3 + 7)

    # WorldMemory (persistent quest-giver / vendor knowledge) — used to attribute
    # return/turn-in navigation to a remembered giver vs a fallback.
    world_mem = WorldMemory()

    # metrics — extended per user audit (2026-08-20). These separate real
    # long-horizon autonomy from short-loop survival, and are the acceptance
    # criteria for the self-learning stage (esp. quest_turnin_rate).
    m = {
        "steps": 0, "kills": 0, "quests_accepted": 0, "quests_done": 0,
        "deaths": 0, "xp": 0, "copper": 0,
        "unique_npcs": set(), "explored_cells": set(),
        "action_counts": Counter(), "env_errors": 0,
        "neg_lessons": 0, "recovery_after_neg": 0,
        "repeated_mistakes": 0,
        "win_reward": 0.0, "win_deaths": 0, "win_repeat": 0,
        "win_actions": Counter(), "win_steps": 0, "deaths_prev": 0,
        # --- extended autonomy metrics ---
        "quests_completed": 0,        # objectives done, awaiting turn-in
        "quests_turned_in": 0,        # actually turned in (verifier SUCCESS)
        "quest_turnin_failures": 0,    # turn_in attempted but FAILURE/INCONCLUSIVE
        "giver_memory_hits": 0,       # return/turn-in used a remembered giver
        "giver_memory_misses": 0,      # return/turn-in had no remembered giver (fallback)
        "vendors_found": 0,            # distinct vendor NPCs ever seen
        "vendor_navigation_success": 0,
        "items_sold": 0,               # sell_junk SUCCESS (inventory shrank)
        "sell_failures": 0,
        "navigation_success": 0,       # return/turn_in arrived (SUCCESS)
        "navigation_stuck": 0,         # return/turn_in PARTIAL repeatedly (no progress)
        "navigation_recovery": 0,      # stuck -> later arrived
        "programming_errors": 0,       # FATAL crash from a code bug (should be 0)
        "bridge_errors": 0,            # ENV_ERROR recoveries (infra)
        "goal_switches": 0,            # policy changed action category vs prev step
        "goal_completed": 0,           # a goal (quest) reached DONE
        "episodes": 1,                 # restarts count as new episodes
        "respawns": 0,
        "reward_mean": 0.0,            # running mean over steps
        "reward_window": 0.0,          # last-window sum (alias of win_reward)
        "prev_goal": None,
        "_last_turnin_partial": False,
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

    # INIT RESPAWN: if the character is already dead (ghost / hp depleted) at
    # startup, revive BEFORE the first step so the agent never begins a learning
    # episode from a broken state. Without this the agent would call explore on a
    # dead body, the bridge exploreWalk may stall, and faulthandler would kill it
    # before the in-loop respawn-glue (which only runs AFTER a completed step).
    try:
        _p0 = (env._last_info or {}).get("player", {}) or {}
        if _p0.get("dead") or _p0.get("hp", 1) <= 0:
            print("[autonomous] init: character dead at startup -> respawning")
            env.respawn()
            m["respawns"] += 1
    except Exception as e:
        # respawn failure at init is infra, not a programming bug; log and continue
        sys.stderr.write(f"[autonomous] init respawn failed (continuing): {type(e).__name__}: {e}\n")

    prev = snap(env._last_info)
    start = time.time()

    for i in range(N_STEPS):
        try:
            if MEASURE_EVERY > 0 and i > 0 and i % MEASURE_EVERY == 0:
                # FROZEN EVAL: measure current policy WITHOUT learning (exploration
                # bonus off, no weight update). The resulting verdict/reward still
                # flow into metrics, but memory is untouched -> BEFORE/AFTER valid.
                rec = agent.step_no_learn(exploration_weight=0.0)
                rec = dict(rec)
                rec["verdict"] = (rec.get("verdict") or "") + " [MEASURE]"
            else:
                rec = agent.step()
        except BrowserBridgeError:
            # Infra failure (bridge/CDP/HTTP down). Same category as ENV_ERROR:
            # recover by re-init'ing the env, keep learning. NOT a programming bug.
            m["env_errors"] += 1
            m["bridge_errors"] += 1
            m["episodes"] += 1
            try:
                env.close()
            except Exception:
                pass
            env = BrowserEnv(player_class="warrior", max_steps=100000, seed=SEED + i)
            env.reset(seed=SEED + i)
            agent = Agent(env, mem, seed=SEED * 3 + 7 + i)
            rec = {"action": "RESTART", "verdict": "ENV_ERROR", "outcome_kind": "ENV_ERROR",
                   "reward": 0.0, "ws_before": prev, "ws_after": snap(env._last_info)}
        except Exception:
            # PROGRAMMING BUG (NameError/KeyError/TypeError/AssertionError/...).
            # Must NOT be masked as a silent restart — crash loudly with traceback
            # so the broken code is found (acceptance test #3). Flush the loop.
            m["programming_errors"] += 1
            traceback.print_exc()
            sys.stderr.write(
                f"[autonomous] FATAL programming error at step {i}: aborting run "
                f"(memory saved at {EXP_PATH})\n"
            )
            mem.save()
            try:
                if os.path.exists(LOCK_PATH):
                    os.remove(LOCK_PATH)
            except OSError:
                pass
            sys.exit(1)

        # respawn glue: if the character died (hp depleted OR stuck as a ghost
        # with dead:true but full hp), release spirit + revive so the loop keeps
        # collecting honest signal (does NOT mutate the model). The game reports
        # dead:true with hp refilled after death, so hp_frac<=0 alone misses it.
        _ws = rec.get("ws_after", {}) or {}
        _dead = _ws.get("dead") or (env._last_info.get("player", {}) or {}).get("dead")
        if _ws.get("hp_frac", 1.0) <= 0.0 or _dead or _ws.get("deaths", 0) > m["deaths"]:
            try:
                env.respawn()
                m["respawns"] += 1
                rec["ws_after"] = snap(env._last_info)
            except BrowserBridgeError as e:
                # respawn can fail if the bridge is mid-reconnect or the game
                # tab is not ready. Do NOT crash the whole process — record a
                # bridge_error and re-init the env on the next iteration so the
                # launcher's restart loop is not triggered by a transient
                # respawn failure.
                m["bridge_errors"] += 1
                print("respawn bridge_error: %s" % e, flush=True)
                env = BrowserEnv(player_class="warrior", max_steps=100000, seed=SEED + i)
                env.reset(seed=SEED + i)
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
        ready = info.get("quests", {}).get("ready") or []
        done = info.get("quests", {}).get("done") or []
        m["quests_accepted"] = max(m["quests_accepted"], len(active) + len(ready) + len(done))
        m["quests_done"] = max(m["quests_done"], len(done))
        m["quests_completed"] = max(m["quests_completed"], len(ready) + len(done))
        # vendors: distinct vendor NPCs ever seen nearby
        for e in (info.get("nearby") or []):
            if (e.get("kind") == "npc" or e.get("type") == "npc") and \
               (e.get("vendor") or e.get("vendorItems") or e.get("isVendor")):
                m["unique_npcs"].add("vendor:" + str(e.get("id") or e.get("name")))
        m["vendors_found"] = len([u for u in m["unique_npcs"] if str(u).startswith("vendor:")])
        # --- event counters from this step's action/verdict ---
        verdict = rec["verdict"]
        prev_inv = (rec["ws_before"] or {}).get("inv_slots", 0)
        cur_inv = ws.get("inv_slots", 0)
        if a == "accept_quest" and verdict in ("SUCCESS", "INCONCLUSIVE"):
            # accept counted via quests_accepted growth; track turn-in outcomes below
            pass
        if a == "turn_in_quest":
            if verdict == "SUCCESS":
                m["quests_turned_in"] += 1
                m["navigation_success"] += 1
            elif verdict in ("FAILURE", "INCONCLUSIVE"):
                m["quest_turnin_failures"] += 1
                if verdict == "INCONCLUSIVE":
                    m["navigation_stuck"] += 1
                m["_last_turnin_partial"] = (verdict == "INCONCLUSIVE")
            # attribute to remembered giver (WorldMemory) vs fallback
            qid = (rec.get("ws_after", {}) or {}).get("quest_status")
            if world_mem.giver_pos(str((active + ready + done and (active + ready + done)[0].get("id", "")) or "")):
                m["giver_memory_hits"] += 1
            else:
                m["giver_memory_misses"] += 1
        if a == "return_to_giver":
            if verdict == "SUCCESS":
                m["navigation_success"] += 1
                if m["_last_turnin_partial"]:
                    m["navigation_recovery"] += 1
            elif verdict == "PARTIAL":
                m["navigation_stuck"] += 1
            if world_mem.giver_pos(str((active + ready + done and (active + ready + done)[0].get("id", "")) or "")):
                m["giver_memory_hits"] += 1
            else:
                m["giver_memory_misses"] += 1
        if a == "sell_junk":
            if verdict == "SUCCESS":
                m["items_sold"] += 1
                m["vendor_navigation_success"] += 1
            elif verdict in ("FAILURE", "INCONCLUSIVE"):
                m["sell_failures"] += 1
        # goal switch: policy changed high-level intent vs previous step
        goal_cat = a
        if m["prev_goal"] is not None and goal_cat != m["prev_goal"]:
            m["goal_switches"] += 1
        m["prev_goal"] = goal_cat
        # goal completed: a quest reached DONE this step
        if len(done) > m.get("_done_prev", 0):
            m["goal_completed"] += (len(done) - m.get("_done_prev", 0))
        m["_done_prev"] = len(done)
        # running reward mean
        m["reward_mean"] = (m["reward_mean"] * (m["steps"] - 1) + rec["reward"]) / m["steps"]
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
    # release the single-instance lock so a future launch can start cleanly
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except OSError:
        pass


def _summary(m, i, start, logf, final=False):
    el = time.time() - start
    # главный показатель долгосрочной автономности
    qtr = (m["quests_turned_in"] / m["quests_completed"]) if m["quests_completed"] else 0.0
    gm_hit = m["giver_memory_hits"]
    gm_miss = m["giver_memory_misses"]
    gm_rate = (gm_hit / (gm_hit + gm_miss)) if (gm_hit + gm_miss) else 0.0
    msg = (f"\n=== {'FINAL' if final else f'step {i}'} autonomous summary "
           f"(t={el:.0f}s, {m['steps']} steps) ===\n"
           f"  kills={m['kills']} quests_accepted={m['quests_accepted']} "
           f"quests_completed={m['quests_completed']} quests_turned_in={m['quests_turned_in']}\n"
           f"  QUEST_TURNIN_RATE={qtr:.2%}  goal_completed={m['goal_completed']} deaths={m['deaths']} respawns={m['respawns']}\n"
           f"  xp={m['xp']} copper={m['copper']} explored_cells={len(m['explored_cells'])} "
           f"unique_npcs={len(m['unique_npcs'])} env_errors={m['env_errors']}\n"
           f"  giver_memory: hits={gm_hit} misses={gm_miss} rate={gm_rate:.0%}\n"
           f"  vendors_found={m['vendors_found']} items_sold={m['items_sold']} sell_failures={m['sell_failures']}\n"
           f"  nav_success={m['navigation_success']} nav_stuck={m['navigation_stuck']} nav_recovery={m['navigation_recovery']}\n"
           f"  quest_turnin_failures={m['quest_turnin_failures']} programming_errors={m['programming_errors']} bridge_errors={m['bridge_errors']} episodes={m['episodes']}\n"
           f"  neg_lessons={m['neg_lessons']} repeated_mistakes={m['repeated_mistakes']} "
           f"recovery_after_neg={m['recovery_after_neg']} goal_switches={m['goal_switches']}\n"
           f"  reward_mean={m['reward_mean']:+.3f} actions={dict(m['action_counts'])}\n")
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
