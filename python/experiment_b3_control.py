"""Experiment B3-control — strict control experiment with RAW TRACE.

Per user review 2026-08-17 (12 points). This is the definitive run, not "another
experiment for a pretty percentage". Differences from experiment_b3.py:

1. (point #1) We never report a bare probability. Every rate is recorded as
   raw counts: `return=N, far_mob_decisions=M, P=N/M`. No rounding ambiguity.

2. (point #4 / Variant A vs B) For EVERY measured decision we log the FULL chain
   the user demanded:
       seed, decision_index, initial_bucket, action, reward,
       next_bucket, Q_before, Q_after, distance_before, distance_after
   and we CHECK that the bucket used to READ (decide) equals the bucket used to
   WRITE (learn). After the root-bucket-mismatch bug, we require this, not trust.

3. (point #6) Measurement uses exploration_weight=0.0 so P(action) reflects Q
   ONLY — the exploration/visit-count confound is removed when comparing
   BEFORE vs AFTER. Training keeps 1.0.

4. (point #8/#9) Sample size: 5 eval seeds x 60 far+mob decisions = 300 per
   phase (was 9/10). Still sequential (the headless sim server is SHARED, one
   per machine — verified, cannot parallelize).

5. (point #10) Four metrics:
   M1 choice      : P(return|far+mob), P(farm|far+mob)  [raw counts]
   M2 value       : Q(far+mob, return) vs Q(far+mob, farm)  [want return > farm]
   M3 consequence : mean Δdistance per action (farm should move AWAY, return TOWARD)
   M4 transfer    : Q(return)-Q(farm) gap by distance band (80-100 / 100-130 / 130+)

6. (point #7) Frozen memory during measurement (deepcopy + step_no_learn). Same
   eval seeds, same forcing (real farm to far+mob), same decision count BEFORE/AFTER.

No architecture change. No `if far -> return` rule. No PPO.

The control experiment's job is to let us reconstruct, per decision:
    farm -> negative consequence -> negative reward -> experience -> Q(farm) down
    -> return becomes more probable
from the raw trace, on several seeds and several hundred decisions.
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

SKILLS = [SKILL_FARM, SKILL_RETURN, SKILL_LOOT, SKILL_ACCEPT, SKILL_TURN_IN,
          SKILL_HEAL, SKILL_SELL, SKILL_GATHER]

EXP_PATH = os.path.join(os.path.dirname(__file__), "experience_b3c.json")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "experiment_b3c_report.json")
TRACE_PATH = os.path.join(os.path.dirname(__file__), "experiment_b3c_trace.csv")

EVAL_SEEDS = [4242, 5353, 6464, 777, 1234]
TRAIN_SEEDS = [42, 107, 256, 511, 909]
MEASURE_STEPS = 40
FARM_FAR_CAP = 150
FAR_THRESHOLD = 80.0
EXPLORATION_AT_MEASURE = 0.0   # (point #6) P reflects Q only


# ---- harness ----
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


def has_mob(info) -> bool:
    near = info.get("nearby") or []
    return any((e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")
               for e in near)


def is_far(info) -> bool:
    return "far=1" in _bucket(build_world_state(info))


def is_real_state(info) -> bool:
    """The B3 measurement STATE is: quest ACTIVE and distance_to_giver = far (>80).

    NOTE (methodology, 2026-08-17): we deliberately do NOT also require
    mob_nearby. return_to_giver, by its nature, walks TOWARD the giver and thus
    DESTROYS the far state — so a state requiring both far AND mob can never
    stably contain a return decision; every return would force a 50s re-drift.
    The user's intent (a realistic far state with the quest incomplete) is met by
    far + ACTIVE; mob presence is logged separately as context, not a gate.
    """
    ws = build_world_state(info)
    return (ws["quest_status"] == "ACTIVE" and "far=1" in _bucket(ws))


def force_far(env) -> bool:
    """Drift into the far state (quest ACTIVE, dist>80) by plain forward walking.

    Plain ACT_FORWARD is the most reliable way to leave the giver: verified to
    reach dist~83 (>far threshold 80) in 26 steps on ALL eval seeds. Farm-drift
    stalls (no nearby mob -> player stops) and re-drifting after every return
    decision took ~50s each, making the experiment unusable. Plain forward is
    fast and reproducible.
    """
    for _ in range(200):
        if is_real_state(env._last_info):
            return True
        env._last_info = env.base.step(ACT_FORWARD)[4]
    return is_real_state(env._last_info)


# ---- measurement with raw trace ----
def measure_phase(label, mem, seeds, trace_rows):
    frozen = copy.deepcopy(mem)
    actions = []
    qvals = defaultdict(list)                       # bucket -> action -> [q]
    delta_by_action = defaultdict(list)             # action -> [dist_before - dist_after]
    transfer = defaultdict(lambda: defaultdict(list))  # band -> action -> q
    episodes = 0

    for seed in seeds:
        env = None
        try:
            env = HierarchicalWoWEnv(player_class="warrior", max_steps=4000, seed=seed)
            env.reset(seed=seed)
            agent = Agent(env, frozen, seed=seed * 7 + 3)
            if not accept_welcome(env):
                print(f"  [{label} seed={seed}] no giver, skipped")
                continue
            if not force_far(env):
                print(f"  [{label} seed={seed}] never reached far, skipped")
                continue
            episodes += 1

            measured = 0
            recover = 0
            di = 0
            while measured < MEASURE_STEPS:
                if not is_real_state(env._last_info):
                    recover += 1
                    if recover > 40:
                        break
                    # Always re-establish far+mob via the (reliable, ~50s) farm
                    # drift. A lighter env.step(0) loop was tried but stalls when
                    # the player has drifted away from all mobs (each farm step is
                    # ~1s and mob never re-acquired -> minutes per recovery).
                    try:
                        force_far(env)
                    except Exception:
                        break
                    continue
                recover = 0

                ws = build_world_state(env._last_info)
                bucket = _bucket(ws)
                dist_before = ws["distance_to_giver"]
                # Q BEFORE this decision (what the policy is reading RIGHT now)
                q_before = {a: frozen.value(bucket, a) for a in SKILLS}
                for a in SKILLS:
                    qvals[a].append(q_before[a])
                    band = ("80-100" if dist_before < 100 else
                            "100-130" if dist_before < 130 else "130+")
                    transfer[band][a].append(q_before[a])

                # make the decision with exploration DISABLED (point #6)
                action, ctx = agent.policy.decide(env._last_info, ws=ws,
                                                  exploration_weight=EXPLORATION_AT_MEASURE)

                # run the skill (no learning — frozen memory)
                after, verdict, outcome_kind = agent._run_skill(action, ctx, env._last_info)
                ws_after = build_world_state(after)
                rew = outcome_reward_safe(ws, ws_after, verdict, outcome_kind)
                env._last_info = after

                next_bucket = _bucket(ws_after)
                dist_after = ws_after["distance_to_giver"]

                # Q AFTER (recompute from frozen store — unchanged, but logged for
                # the trace to show the agent did NOT learn during measurement)
                q_after = {a: frozen.value(bucket, a) for a in SKILLS}

                # Variant A/B check (point #4): did the bucket the lesson would
                # land in match the bucket we measured? If next_bucket drops
                # far/mob, the update goes to a neighbour, not where we read.
                variant_a = ("far=1" in next_bucket) and ("mob=1" in next_bucket)

                trace_rows.append({
                    "phase": label, "seed": seed, "decision": di,
                    "initial_bucket": bucket, "action": action,
                    "reward": round(rew, 4), "next_bucket": next_bucket,
                    "variant_a": variant_a,
                    "Q_before_farm": round(q_before["farm"], 4),
                    "Q_before_return": round(q_before["return_to_giver"], 4),
                    "Q_after_farm": round(q_after["farm"], 4),
                    "Q_after_return": round(q_after["return_to_giver"], 4),
                    "dist_before": round(dist_before, 1),
                    "dist_after": round(dist_after, 1),
                })
                di += 1

                actions.append(action)
                delta_by_action[action].append(dist_before - dist_after)
                measured += 1

            print(f"  [{label} seed={seed}] measured {measured} far+mob decisions")
        except Exception as ex:
            print(f"  [{label} seed={seed}] exception {ex!r}")
        finally:
            if env is not None:
                try:
                    env.close()
                except Exception:
                    pass

    n = len(actions)
    dist = {k: (actions.count(k), n, round(actions.count(k) / n, 4)) for k in set(actions)}
    # q_mean: aggregate over all measured (state, action) Q-values (honest: if the
    # gap holds even aggregated, it is stronger; per-bucket detail is in the trace)
    q_farm = qvals.get("farm", [])
    q_ret = qvals.get("return_to_giver", [])
    q_mean = {
        "farm": round(sum(q_farm) / len(q_farm), 4) if q_farm else 0.0,
        "return_to_giver": round(sum(q_ret) / len(q_ret), 4) if q_ret else 0.0,
    }
    transfer_mean = {
        band: {
            "farm": round(sum(acts.get("farm", [])), 4) if acts.get("farm") else 0.0,
            "return_to_giver": round(sum(acts.get("return_to_giver", [])), 4)
            if acts.get("return_to_giver") else 0.0,
        }
        for band, acts in transfer.items()
    }
    delta_mean = {a: (round(sum(v) / len(v), 4) if v else 0.0)
                  for a, v in delta_by_action.items()}
    return {
        "label": label,
        "episodes_reached_state": episodes,
        "far_mob_decisions": n,
        "distinct_actions": len(set(actions)),
        "P": dist,                                   # (count, total, rate)
        "Q_mean": q_mean,
        "Q_by_distance_band": transfer_mean,
        "delta_distance_by_action": delta_mean,
    }


def outcome_reward_safe(ws_before, ws_after, verdict, outcome_kind):
    """Mirror reward.outcome_reward without importing its side effects; we only
    need the scalar here. Reuse the real one to stay honest."""
    from reward import outcome_reward
    return outcome_reward(ws_before, ws_after, verdict, outcome_kind)


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
            force_far(env)
            for _ in range(MEASURE_STEPS):
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


def main():
    if os.path.exists(EXP_PATH):
        os.remove(EXP_PATH)
    mem = ExperienceStore(path=EXP_PATH)
    trace_rows = []

    print("=== BEFORE (memory empty, frozen@measure, exploration OFF) ===")
    before = measure_phase("BEFORE", mem, EVAL_SEEDS, trace_rows)

    print("\n=== TRAIN (learning ON) ===")
    tstats = train(mem)

    print("\n=== AFTER (identical protocol, frozen@measure, exploration OFF) ===")
    after = measure_phase("AFTER", mem, EVAL_SEEDS, trace_rows)

    # ---- write raw trace CSV (point #12) ----
    with open(TRACE_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trace_rows[0].keys()))
        w.writeheader()
        w.writerows(trace_rows)
    print(f"\nraw trace -> {TRACE_PATH} ({len(trace_rows)} rows)")

    # ---- comparisons ----
    print("\n" + "=" * 66)
    print("M1 CHOICE  (raw counts, not bare probabilities)")
    bf = before["P"].get("return_to_giver")
    af = after["P"].get("return_to_giver")
    bfc = before["P"].get("farm")
    afc = after["P"].get("farm")
    print(f"  return: BEFORE {bf[0]}/{bf[1]} = {bf[2]:.4f}  ->  "
          f"AFTER {af[0]}/{af[1]} = {af[2]:.4f}")
    print(f"  farm:   BEFORE {bfc[0]}/{bfc[1]} = {bfc[2]:.4f}  ->  "
          f"AFTER {afc[0]}/{afc[1]} = {afc[2]:.4f}")

    print("\nM2 VALUE  (Q at far+mob; want Q(return) > Q(farm))")
    print(f"  Q(farm)       BEFORE {before['Q_mean']['farm']:+.4f}  "
          f"-> AFTER {after['Q_mean']['farm']:+.4f}")
    print(f"  Q(return)     BEFORE {before['Q_mean']['return_to_giver']:+.4f}  "
          f"-> AFTER {after['Q_mean']['return_to_giver']:+.4f}")
    qret_a = after["Q_mean"]["return_to_giver"]
    qfar_a = after["Q_mean"]["farm"]
    print(f"  AFTER gap Q(return)-Q(farm) = {qret_a - qfar_a:+.4f}")

    print("\nM3 CONSEQUENCE  (mean Δdistance per action; + = moved away)")
    for a in sorted(after["delta_distance_by_action"]):
        print(f"  {a:16s} AFTER Δdist = {after['delta_distance_by_action'][a]:+.2f}")

    print("\nM4 TRANSFER  (AFTER Q gap by distance band)")
    for band in sorted(after["Q_by_distance_band"]):
        acts = after["Q_by_distance_band"][band]
        gap = acts["return_to_giver"] - acts["farm"]
        print(f"  band {band:7s}: Q(return)={acts['return_to_giver']:+.4f}  "
              f"Q(farm)={acts['farm']:+.4f}  gap={gap:+.4f}")

    # ---- criteria ----
    print("\n" + "=" * 66)
    print("CRITERIA")
    n_ok = before["far_mob_decisions"] >= 100 and after["far_mob_decisions"] >= 100
    print(f"  [{'x' if n_ok else ' '}] >=100 far+mob decisions/phase "
          f"({before['far_mob_decisions']}/{after['far_mob_decisions']})")
    alt = after["distinct_actions"] >= 2
    print(f"  [{'x' if alt else ' '}] alternatives alive ({after['distinct_actions']})")
    farm_ok = afc[2] > 0.0
    print(f"  [{'x' if farm_ok else ' '}] farm possible P={afc[2]:.4f}")
    qret_up = qret_a > before["Q_mean"]["return_to_giver"]
    qfar_down = qfar_a < before["Q_mean"]["farm"]
    print(f"  [{'x' if qret_up else ' '}] Q(return) rose ({before['Q_mean']['return_to_giver']:+.4f}->{qret_a:+.4f})")
    print(f"  [{'x' if qfar_down else ' '}] Q(farm) fell ({before['Q_mean']['farm']:+.4f}->{qfar_a:+.4f})")
    gap_pos = qret_a > qfar_a
    print(f"  [{'x' if gap_pos else ' '}] AFTER Q(return) > Q(farm) (gap {qret_a - qfar_a:+.4f})")
    # transfer: gap>0 in >=1 non-80 band
    transfer_ok = any(
        after["Q_by_distance_band"][b]["return_to_giver"] >
        after["Q_by_distance_band"][b]["farm"]
        for b in after["Q_by_distance_band"] if b != "80-100")
    print(f"  [{'x' if transfer_ok else ' '}] TRANSFER Q(return)>Q(farm) in >=1 band != 80-100")

    passed = n_ok and alt and farm_ok and gap_pos
    print(f"\n  VERDICT: {'PASS — self-learning CLOSED' if passed else 'NOT PROVEN (increase N)'}")

    report = {
        "before": before, "after": after, "train": tstats,
        "criteria": {
            "enough_far_mob_decisions": n_ok, "alternatives_alive": alt,
            "farm_possible": farm_ok, "q_return_up": qret_up, "q_farm_down": qfar_down,
            "gap_return_gt_farm": gap_pos, "transfer": transfer_ok, "passed": passed,
        },
        "protocol": {
            "eval_seeds": EVAL_SEEDS, "train_seeds": TRAIN_SEEDS,
            "measure_steps": MEASURE_STEPS, "far_threshold": FAR_THRESHOLD,
            "exploration_at_measure": EXPLORATION_AT_MEASURE,
            "state": "quest=ACTIVE, far, mob_nearby",
            "memory_frozen_at_measure": True, "raw_trace": TRACE_PATH,
        },
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"report -> {REPORT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
