"""causal_self_learning_test.py — Level 4 CAUSAL proof in the LIVE WoC world.

Strict protocol (user verdict 2026-08-18, step 2). Goal: prove the agent
changes behaviour BECAUSE of its own online experience — not just "does things".

We may FORCE the WORLD STATE (spawn, navigate, accept quest) but NEVER the
learning OUTCOME. The policy chooses autonomously during measurement.

Protocol:
  FORCE (no learning, navigation only):
      spawn -> accept quest (if needed) -> navigate to mob area, far from giver
      wait until bucket S = {far=1, mob=1, qs=ACTIVE, hp=full} exists
  BEFORE (frozen memory, policy autonomous + exploration off):
      measure for bucket S:  Q(S,a), P(a|S), n(S,a)   for a in candidates
  TRAIN (real online steps WITH learning):
      run agent.step() autonomously until we OBSERVE a real (S, farm, negative)
      experience; if the autonomous policy never picks farm, do ONE controlled
      training probe (step_forced("farm", learn=True)) — explicitly separated
      from evaluation. Result still comes from the real world; only the CHOICE
      was forced.
  FREEZE (no learning during measurement)
  AFTER (frozen memory, same bucket S key, policy autonomous + exploration off):
      measure Q(S,a), P(a|S), n(S,a) again
  REPORT deltas + verdict.

Minimal PASS:  real online negative experience in S
           AND  Q_after(S,farm) < Q_before(S,farm)
           AND  P_after(farm|S) < P_before(farm|S)   (non-zero sample)
Strong PASS:   additionally Q_after(S,return) > Q_before(S,return)
                          and P_after(return|S) > P_before(return|S)

Run: python causal_self_learning_test.py   (bridge must be live on :8791)
"""
import os
import sys
import json
import random
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from browser_env import BrowserEnv
from agent import Agent
from memory import ExperienceStore, _bucket
from world_state import build_world_state

EXP_PATH = os.path.join(os.path.dirname(__file__), "experience_autonomous.json")
SEED = 4242
N_TRAIN = int(os.environ.get("CAUSAL_TRAIN", "120"))
N_MEASURE = int(os.environ.get("CAUSAL_MEASURE", "300"))
FORCE_LIMIT = int(os.environ.get("CAUSAL_FORCE", "400"))


def parse_bucket(b: str) -> dict:
    out = {}
    for part in b.split("|"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k] = v
    return out


def bucket_matches(b: str) -> bool:
    f = parse_bucket(b)
    return (f.get("far") == "1" and f.get("mob") == "1"
            and f.get("qs") == "ACTIVE")


def measure(agent, mem, bucket, info, ws, n=N_MEASURE):
    """Frozen measurement: Q/P/n for bucket S. policy decides autonomously with
    exploration OFF (exploration_weight=0) so P reflects Q only — no count-bonus
    confound. Same info+ws used for BEFORE and AFTER (memory is what changes)."""
    q = {a: mem.value(bucket, a) for a in mem.ACTIONS}
    n_count = {a: mem.counts.get((bucket, a), 0) for a in mem.ACTIONS}
    p = Counter()
    for _ in range(n):
        a, _ = agent.policy.decide(info, ws=ws, exploration_weight=0.0)
        p[a] += 1
    total = sum(p.values()) or 1
    P = {a: p.get(a, 0) / total for a in mem.ACTIONS}
    return q, P, n_count


def force_state(agent, env, target_feats):
    """Navigate the live world until bucket S = {far=1,mob=1,qs=ACTIVE} with
    hp>=0.8. Navigation/accept only — NO learning. Returns (ws_S, info_S, bucket)
    or None if not reached within FORCE_LIMIT tries."""
    for it in range(FORCE_LIMIT):
        info = env._last_info
        # respawn if dead — a dead char can never satisfy hp>=0.8
        if (info.get("player", {}) or {}).get("dead"):
            env.respawn()
            info = env._last_info
        ws = build_world_state(info)
        b = _bucket(ws)
        f = parse_bucket(b)
        if it % 10 == 0 or (f.get("far") == "1" and f.get("mob") == "1"
                             and f.get("qs") == "ACTIVE"):
            print(f"[FORCE][{it}] bucket={b} hp={ws.get('hp_frac',0):.2f} "
                  f"dist={ws.get('distance_to_giver',0):.0f} "
                  f"nearby={len(info.get('nearby') or [])}")
        if (f.get("far") == "1" and f.get("mob") == "1"
                and f.get("qs") == "ACTIVE" and ws.get("hp_frac", 0) >= 0.8):
            return ws, info, b
        # drive toward target without learning
        if f.get("qs") != "ACTIVE":
            agent._maybe_accept_welcome()      # find + accept quest if possible
            continue
        # have an ACTIVE quest: find a real mob and walk to it, drift far from giver
        mobs = [e for e in (info.get("nearby") or [])
                if (e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")]
        if mobs:
            m = mobs[0]
            # walk a few steps toward the mob to populate has_mob + distance
            env._navigate_to_coord(m.get("x"), m.get("z"), max_steps=30)
        else:
            env.explore_walk(steps=20)         # move/explore to find mobs & drift far
    return None


def main():
    random.seed(SEED)
    mem = ExperienceStore(path=EXP_PATH)
    env = BrowserEnv(player_class="warrior", max_steps=100000, seed=SEED)
    env.reset(seed=SEED)
    agent = Agent(env, mem, seed=SEED * 3 + 7)

    # ---- FORCE state S (no learning) ----
    forced = force_state(agent, env, None)
    if forced is None:
        print("[FORCE] FAILED to reach bucket S={far=1,mob=1,qs=ACTIVE,hp>=0.8} "
              "within %d nav tries. World/state not available — aborting honestly."
              % FORCE_LIMIT)
        env.close()
        return
    ws_S, info_S, bucket_S = forced
    print(f"[FORCE] reached bucket S = {bucket_S}")

    # ---- BEFORE (frozen) ----
    q_before, p_before, n_before = measure(agent, mem, bucket_S, info_S, ws_S)
    print(f"[BEFORE] Q(S,a): {_fmt(q_before)}")
    print(f"[BEFORE] P(a|S): {_fmt(p_before)}")
    print(f"[BEFORE] n(S,a): {_fmt_int(n_before)}")

    # ---- TRAIN (real online steps with learning) ----
    got_neg = False
    train_recs = []
    for i in range(N_TRAIN):
        rec = agent.step()
        bk = _bucket(rec["ws_before"])
        if bk == bucket_S and rec["action"] == "farm" and rec["reward"] < -0.1:
            got_neg = True
            train_recs.append(rec)
            print(f"[TRAIN] step {i}: REAL (S, farm, negative) r={rec['reward']:+.2f}")
            break
        train_recs.append(rec)
    # controlled probe only if autonomous policy never produced the experience
    if not got_neg:
        print(f"[TRAIN] autonomous policy did not pick farm in S within {N_TRAIN} "
              f"steps — doing ONE controlled training probe (forced farm, learn=True).")
        rec = agent.step_forced("farm", learn=True)
        bk = _bucket(rec["ws_before"])
        if bk == bucket_S and rec["reward"] < -0.1:
            got_neg = True
        train_recs.append(rec)
        print(f"[TRAIN] probe: bucket={bk} action={rec['action']} "
              f"r={rec['reward']:+.2f} (forced choice, real-world result)")
    mem.save()
    print(f"[TRAIN] {len(train_recs)} steps | real_negative_in_S={got_neg}")

    # ---- AFTER (frozen, same bucket key) ----
    q_after, p_after, n_after = measure(agent, mem, bucket_S, info_S, ws_S)
    print(f"[AFTER]  Q(S,a): {_fmt(q_after)}")
    print(f"[AFTER]  P(a|S): {_fmt(p_after)}")
    print(f"[AFTER]  n(S,a): {_fmt_int(n_after)}")

    # ---- deltas ----
    dq = {a: round(q_after[a] - q_before[a], 4) for a in mem.ACTIONS}
    dp = {a: round(p_after[a] - p_before[a], 4) for a in mem.ACTIONS}
    dn = {a: n_after[a] - n_before[a] for a in mem.ACTIONS}
    print(f"[DELTA]  dQ(S,a): {_fmt(dq)}")
    print(f"[DELTA]  dP(a|S): {_fmt(dp)}")
    print(f"[DELTA]  dn(S,a): {_fmt_int(dn)}")

    # ---- verdict ----
    q_drop = q_after["farm"] < q_before["farm"] - 1e-6
    p_drop = p_after["farm"] < p_before["farm"] - 0.02
    sampled = n_after["farm"] > 0
    min_pass = got_neg and q_drop and p_drop and sampled
    q_up = q_after["return_to_giver"] > q_before["return_to_giver"] + 1e-6
    p_up = p_after["return_to_giver"] > p_before["return_to_giver"] + 0.02
    strong_pass = min_pass and q_up and p_up

    print(f"[VERDICT] real_negative_in_S = {got_neg}")
    print(f"[VERDICT] Q(farm) dropped    = {q_drop}  ({q_before['farm']:+.3f} -> {q_after['farm']:+.3f})")
    print(f"[VERDICT] P(farm|S) dropped  = {p_drop}  ({p_before['farm']:+.3f} -> {p_after['farm']:+.3f})")
    print(f"[VERDICT] sample n(S,farm)>0 = {sampled} ({n_after['farm']})")
    if strong_pass:
        print("[VERDICT] *** STRONG PASS *** experience -> Q(farm) down, P(farm) down, "
              "AND Q(return)/P(return) up. Causal chain + alternative learned.")
    elif min_pass:
        print("[VERDICT] *** MINIMAL PASS *** experience -> Q(farm) down + P(farm) down "
              "(non-zero sample). Causal chain proven.")
    else:
        print("[VERDICT] NO PASS — state/event not achieved or Q/P did not move as required.")
    env.close()


def _fmt(d):
    return "{" + ", ".join(f"{k}:{v:+.3f}" for k, v in d.items()) + "}"


def _fmt_int(d):
    return "{" + ", ".join(f"{k}:{v}" for k, v in d.items()) + "}"


if __name__ == "__main__":
    main()
