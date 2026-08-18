"""Experiment B4 — trajectory-bucket + transfer control experiment.

Per user review 2026-08-17 (final B4 spec). This is NOT "another B3 run with more
seeds". It answers three SEPARATE questions the user separated:

  Q1 (architecture/loop): does Q change from real consequences?  -> proven elsewhere
  Q2 (capability): can the agent DISCOVER return is useful?      -> this experiment
  Q3 (autonomy): does it PREFER return over farm at far, on its own? -> the gate

Design (user's exact spec):
- TRAIN: normal loop, random exploration -> real reward -> memory. NO intervention,
  NO `if far -> return`, NO artificial return reward. Frozen after.
- FROZEN EVAL: memory deep-copied, exploration_weight=0.0 (policy.py supports it),
  so P(action|state) depends on learned Q ONLY.
- Measure across a TRAJECTORY of distance bands, not one far-bucket:
      90-100, 70-90, 40-70, 15-40, <15
  For each band: Q(farm), Q(return), P(farm), P(return).
- TRANSFER: train on 90-100, then eval on UNSEEN 110-130 band. If Q(return)>Q(farm)
  there too, the agent generalized, not just memorized buckets.
- Per-decision raw log (user's field list):
      state_bucket, distance_to_giver, has_mob, quest_status,
      action, Q(action), reward, next_bucket, next_distance, outcome_kind

No reward change. No Sim change. No PPO. No policy logic change. Only logging +
bucket-structured measurement. The shared headless server is single-instance, so
this runs sequentially (verified).
"""

import copy
import csv
import json
import os
import sys
from collections import Counter, defaultdict

from hierarchical_env import (HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT)
from agent import Agent
from memory import ExperienceStore, _bucket
from quest_capability import QuestCapability
from world_state import build_world_state
from policy import (SKILL_FARM, SKILL_RETURN, SKILL_LOOT, SKILL_ACCEPT,
                    SKILL_TURN_IN, SKILL_HEAL, SKILL_SELL, SKILL_GATHER)
from reward import outcome_reward

SKILLS = [SKILL_FARM, SKILL_RETURN, SKILL_LOOT, SKILL_ACCEPT, SKILL_TURN_IN,
          SKILL_HEAL, SKILL_SELL, SKILL_GATHER]

EXP_PATH = os.path.join(os.path.dirname(__file__), "experience_b4.json")
BEFORE_PATH = os.path.join(os.path.dirname(__file__), "experience_b4_before.json")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "experiment_b4_report.json")
TRACE_PATH = os.path.join(os.path.dirname(__file__), "experiment_b4_trace.csv")

TRAIN_SEEDS = [42, 107, 256, 511, 909, 1234, 2024, 31337]
EVAL_SEEDS = [4242, 5353, 6464, 777, 1234]

# distance bands for trajectory measurement (last = UNSEEN transfer band)
BANDS = [(90, 100, "90-100"), (70, 90, "70-90"), (40, 70, "40-70"),
         (15, 40, "15-40"), (0, 15, "<15"), (110, 130, "110-130-UNSEEN")]
MEASURE_PER_BAND = 12
EXPLORATION_AT_MEASURE = 0.0   # P reflects Q only (point #6)


def accept_welcome(env) -> bool:
    cap = QuestCapability(env)
    if cap.find_active_quest() is not None:
        return True
    giver = None
    for _ in range(24):
        env.base.step(ACT_FORWARD)
        env.base.step(ACT_TURN_LEFT)
        near = env._last_info.get("nearby") or []
        g = [e for e in near
             if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
        if g:
            giver = g[0]
            break
    if not giver:
        return False
    qid = (giver.get("questIds") or [None])[0]
    env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
    env._last_info = env.base.accept_quest(str(qid))
    return True


def is_active(info) -> bool:
    return build_world_state(info)["quest_status"] == "ACTIVE"


def dist_of(info) -> float:
    return build_world_state(info)["distance_to_giver"]


def has_mob(info) -> bool:
    near = info.get("nearby") or []
    return any((e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")
               for e in near)


def force_to_band(env, lo, hi) -> bool:
    """Walk (plain forward) until distance_to_giver is within [lo, hi)."""
    for _ in range(250):
        d = dist_of(env._last_info)
        if lo <= d < hi:
            return True
        env._last_info = env.base.step(ACT_FORWARD)[4]
    return lo <= dist_of(env._last_info) < hi


def band_of(d):
    for lo, hi, name in BANDS:
        if lo <= d < hi:
            return name
    return "other"


def train(mem):
    stats = {"episodes": 0, "steps": 0, "env_errors": 0}
    for i, seed in enumerate(TRAIN_SEEDS):
        env = None
        try:
            env = HierarchicalWoWEnv(player_class="warrior", max_steps=4000, seed=seed)
            env.reset(seed=seed)
            agent = Agent(env, mem, seed=seed * 3 + 1)
            if not accept_welcome(env):
                print(f"  [train ep{i} seed={seed}] no giver, skipped")
                continue
            force_to_band(env, 90, 100)   # train in the canonical far band
            for _ in range(40):
                try:
                    rec = agent.step()
                except Exception:
                    break
                stats["steps"] += 1
                if rec.get("outcome_kind") == "ENV_ERROR":
                    stats["env_errors"] += 1
                    break
            stats["episodes"] += 1
            print(f"  [train ep{i} seed={seed}] weights={len(mem.weights)} "
                  f"exp={len(mem.experiences)}")
        except Exception as ex:
            print(f"  [train ep{i} seed={seed}] exception {ex!r}")
        finally:
            if env is not None:
                try:
                    env.close()
                except Exception:
                    pass
    mem.save()
    return stats


def measure_band(agent, env, lo, hi, n, trace_rows, phase, seed):
    """Force into [lo,hi), measure n decisions (frozen mem, exploration OFF)."""
    if not force_to_band(env, lo, hi):
        return None
    band = band_of(dist_of(env._last_info))
    local = {"actions": Counter(), "q_farm": [], "q_ret": []}
    for _ in range(n):
        info = env._last_info
        if not is_active(info):
            break
        ws = build_world_state(info)
        bucket = _bucket(ws)
        d0 = ws["distance_to_giver"]
        q_farm = agent.policy.mem.value(bucket, SKILL_FARM)
        q_ret = agent.policy.mem.value(bucket, SKILL_RETURN)
        action, ctx = agent.policy.decide(info, ws=ws,
                                          exploration_weight=EXPLORATION_AT_MEASURE)
        after, verdict, outcome_kind = agent._run_skill(action, ctx, info)
        ws_after = build_world_state(after)
        rew = outcome_reward(ws, ws_after, verdict, outcome_kind)
        env._last_info = after
        next_bucket = _bucket(ws_after)
        next_d = ws_after["distance_to_giver"]
        local["actions"][action] += 1
        local["q_farm"].append(q_farm)
        local["q_ret"].append(q_ret)
        trace_rows.append({
            "phase": phase, "band": band, "seed": seed,
            "state_bucket": bucket, "distance_to_giver": round(d0, 1),
            "has_mob": int(has_mob(info)), "quest_status": ws["quest_status"],
            "action": action,
            "Q_action_farm": round(q_farm, 4),
            "Q_action_return": round(q_ret, 4),
            "reward": round(rew, 4),
            "next_bucket": next_bucket,
            "next_distance": round(next_d, 1),
            "outcome_kind": outcome_kind,
        })
        force_to_band(env, lo, hi)
    if not local["actions"]:
        return None
    tot = sum(local["actions"].values())
    return {
        "band": band,
        "n": tot,
        "P_farm": (local["actions"].get(SKILL_FARM, 0), tot,
                   round(local["actions"].get(SKILL_FARM, 0) / tot, 4)),
        "P_return": (local["actions"].get(SKILL_RETURN, 0), tot,
                     round(local["actions"].get(SKILL_RETURN, 0) / tot, 4)),
        "Q_farm": round(sum(local["q_farm"]) / len(local["q_farm"]), 4),
        "Q_return": round(sum(local["q_ret"]) / len(local["q_ret"]), 4),
    }


def measure_phase(label, mem, seeds, trace_rows, bands):
    frozen = copy.deepcopy(mem)
    results = {}
    for seed in seeds:
        env = None
        try:
            env = HierarchicalWoWEnv(player_class="warrior", max_steps=4000, seed=seed)
            env.reset(seed=seed)
            agent = Agent(env, frozen, seed=seed * 7 + 3)
            if not accept_welcome(env):
                print(f"  [{label} seed={seed}] no giver, skipped")
                continue
            for (lo, hi, name) in bands:
                m = measure_band(agent, env, lo, hi, MEASURE_PER_BAND, trace_rows, label, seed)
                if m is not None:
                    results.setdefault(name, []).append(m)
                    print(f"  [{label} seed={seed} band={name}] "
                          f"P(ret)={m['P_return'][0]}/{m['P_return'][1]} "
                          f"Q(farm)={m['Q_farm']:+.3f} Q(ret)={m['Q_return']:+.3f}")
        except Exception as ex:
            print(f"  [{label} seed={seed}] exception {ex!r}")
        finally:
            if env is not None:
                try:
                    env.close()
                except Exception:
                    pass
    out = {}
    for name, lst in results.items():
        pf = sum(x["P_farm"][0] for x in lst)
        pr = sum(x["P_return"][0] for x in lst)
        tot = sum(x["P_farm"][1] for x in lst)
        out[name] = {
            "n": tot,
            "P_farm": (pf, tot, round(pf / tot, 4) if tot else 0.0),
            "P_return": (pr, tot, round(pr / tot, 4) if tot else 0.0),
            "Q_farm": round(sum(x["Q_farm"] for x in lst) / len(lst), 4),
            "Q_return": round(sum(x["Q_return"] for x in lst) / len(lst), 4),
        }
    return out


def main():
    for p in (EXP_PATH, BEFORE_PATH, REPORT_PATH, TRACE_PATH):
        if os.path.exists(p):
            os.remove(p)
    trace_rows = []

    # ---- BEFORE: fresh (untrained) memory ----
    print("=== BEFORE (fresh memory, frozen@measure, exploration OFF) ===")
    mem_before = ExperienceStore(path=BEFORE_PATH)
    before = measure_phase("BEFORE", mem_before, EVAL_SEEDS, trace_rows,
                           [(lo, hi, name) for (lo, hi, name) in BANDS if name != "110-130-UNSEEN"])

    # ---- TRAIN: normal loop, no intervention ----
    print("\n=== TRAIN (learning ON, no intervention) ===")
    mem = ExperienceStore(path=EXP_PATH)
    tstats = train(mem)

    # ---- AFTER: trained memory ----
    print("\n=== AFTER (trained memory, frozen@measure, exploration OFF) ===")
    after = measure_phase("AFTER", mem, EVAL_SEEDS, trace_rows,
                          [(lo, hi, name) for (lo, hi, name) in BANDS])

    with open(TRACE_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trace_rows[0].keys()))
        w.writeheader()
        w.writerows(trace_rows)
    print(f"\nraw trace -> {TRACE_PATH} ({len(trace_rows)} rows)")

    # ---- report ----
    print("\n" + "=" * 74)
    print("B4 TRAJECTORY (frozen eval, exploration OFF)")
    print(f"{'band':14s} {'ph':4s} {'P(farm)':>14s} {'P(return)':>14s} {'Q(farm)':>9s} {'Q(ret)':>9s}")
    for name in [n for (_, _, n) in BANDS]:
        if name in before:
            b = before[name]
            print(f"{name:14s} {'BEF':4s} {b['P_farm'][0]:>4d}/{b['P_farm'][1]:<3d}={b['P_farm'][2]:.3f}"
                  f"  {b['P_return'][0]:>4d}/{b['P_return'][1]:<3d}={b['P_return'][2]:.3f}"
                  f"  {b['Q_farm']:>+9.3f} {b['Q_return']:>+9.3f}")
        if name in after:
            a = after[name]
            print(f"{name:14s} {'AFT':4s} {a['P_farm'][0]:>4d}/{a['P_farm'][1]:<3d}={a['P_farm'][2]:.3f}"
                  f"  {a['P_return'][0]:>4d}/{a['P_return'][1]:<3d}={a['P_return'][2]:.3f}"
                  f"  {a['Q_farm']:>+9.3f} {a['Q_return']:>+9.3f}")

    print("\nCRITERIA (autonomy gate)")
    far_bands = ["90-100", "70-90", "40-70"]
    beats = all(after[b]["Q_return"] > after[b]["Q_farm"] for b in far_bands if b in after)
    p_ret_up = any(after[b]["P_return"][2] > 0.30 for b in far_bands if b in after)
    transfer = after.get("110-130-UNSEEN", {})
    transfer_ok = transfer.get("Q_return", 0) > transfer.get("Q_farm", 0)
    print(f"  [{'x' if beats else ' '}] Q(return)>Q(farm) in far bands (90-100/70-90/40-70)")
    print(f"  [{'x' if p_ret_up else ' '}] P(return)>0.30 in >=1 far band")
    print(f"  [{'x' if transfer_ok else ' '}] TRANSFER: Q(return)>Q(farm) in UNSEEN 110-130")
    passed = beats and p_ret_up
    print(f"\n  VERDICT: {'PASS — agent discovered return is useful (autonomy)' if passed else 'NOT PROVEN'}")

    report = {
        "before": before, "after": after, "train": tstats,
        "criteria": {"Q_return_beats_farm_far": beats,
                     "P_return_pref_in_far": p_ret_up,
                     "transfer_unseen_band": transfer_ok, "passed": passed},
        "protocol": {"train_seeds": TRAIN_SEEDS, "eval_seeds": EVAL_SEEDS,
                     "bands": [n for (_, _, n) in BANDS], "measure_per_band": MEASURE_PER_BAND,
                     "exploration_at_measure": EXPLORATION_AT_MEASURE, "raw_trace": TRACE_PATH},
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"report -> {REPORT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
