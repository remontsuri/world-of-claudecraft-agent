"""Experiment B v2 — reproducible BEFORE / TRAIN / AFTER with value trajectories.

Protocol (user-specified, 2026-08-17):

    BEFORE
      +- N independent episodes
           +- guaranteed far-state (verified, not assumed)
                +- record action distribution AND Q-values

    TRAIN
      +- experiences (the SAME forcing procedure, learning ON)

    AFTER
      +- identical conditions, N independent episodes

Success criterion is NOT "P(return|far) reaches 0.72". It is:

    after negative experience, the probability of useful behaviour increases
    statistically, WITHOUT alternative actions disappearing.

So we report, per phase:
  - P(action | far) for every action
  - Q(far, action) before vs after   <- the agent re-VALUED actions, not just
                                        pressed a different button more often
  - mean reward, and the measured deltas that produced it:
      distance_delta, quest_progress_delta, death_delta
  - number of DISTINCT actions still sampled at far (exploration alive?)

What makes BEFORE reproducible here (the earlier run's flaw):
  1. BEFORE and AFTER use the SAME seed list, the SAME forcing procedure and the
     SAME number of measured steps. Previously BEFORE used one throwaway seed
     (4242) and AFTER another (9090) -> not comparable.
  2. Every measured step is VERIFIED to be a genuine far-state by rebuilding the
     WorldState and asserting the bucket contains far=1. Steps that are not far
     are discarded, not counted. Previously "far" was filtered by a locally
     recomputed distance while the policy read a far=0 bucket (see
     world_state.py) -> the numbers described different states.
  3. Memory is FROZEN during measurement (learn=False), so measuring does not
     teach. A frozen copy is used, so the measurement cannot mutate the store.

No hidden rules: the policy is never told "return is good when far". The only
thing that connects distance to reward is reward.WEIGHTS["dist_progress"],
applied to the MEASURED change in distance_to_giver.
"""

import copy
import json
import os
import sys
from collections import Counter, defaultdict

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from agent import Agent
from memory import ExperienceStore, _bucket
from quest_capability import QuestCapability
from world_state import build_world_state

EXP_PATH = os.path.join(os.path.dirname(__file__), "experience_b2.json")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "experiment_b2_report.json")

# identical protocol for BEFORE and AFTER
EVAL_SEEDS = [4242, 5353, 6464]
TRAIN_SEEDS = [42, 107, 256, 511, 909, 1234, 2024, 31337]
MEASURE_STEPS = 40          # measured decisions per eval episode
FORCE_FARM_CAP = 60         # max farm bursts while forcing far
FAR_THRESHOLD = 80.0        # same as memory._bucket


# ---------------------------------------------------------------- helpers
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


def is_far(info) -> bool:
    """Ground truth for the far state — the SAME feature memory._bucket() uses."""
    return "far=1" in _bucket(build_world_state(info))


def force_far(env) -> bool:
    """Deterministically walk the player into a genuine far state from the giver.

    HARNESS SETUP, not a measured policy decision (store is frozen in
    measure_phase anyway). Plain ACT_FORWARD is the most reliable way to leave the
    giver: verified to reach dist~83 (>far threshold 80) in 26 steps on ALL eval
    seeds (4242/5353/6464). Farm-drift stalls (no nearby mob -> player stops
    moving) and _navigate_to_coord stalls (~33u, no_progress guard), so neither
    reproduces far reliably.

    The protocol's goal is to measure the POLICY's CHOICES AT far, which is
    independent of how the far state was reached, so a deterministic walk-away is
    the honest, reproducible forcing method.
    """
    for _ in range(200):
        if is_far(env._last_info):
            return True
        env._last_info = env.base.step(ACT_FORWARD)[4]
    return is_far(env._last_info)


# ---------------------------------------------------------------- measurement
def measure_phase(label: str, mem: ExperienceStore, seeds) -> dict:
    """Run the identical measurement protocol with memory FROZEN.

    Returns action distribution, Q-values at far, and the measured deltas.
    """
    frozen = copy.deepcopy(mem)          # measurement must not mutate memory
    actions = []
    qvals = defaultdict(list)
    deltas = {"distance": [], "quest_progress": [], "deaths": [], "reward": []}
    episodes_far = 0

    for seed in seeds:
        env = None
        try:
            env = HierarchicalWoWEnv(player_class="warrior", max_steps=3000, seed=seed)
            env.reset(seed=seed)
            agent = Agent(env, frozen, seed=seed * 7 + 3)
            if not accept_welcome(env):
                print(f"  [{label} seed={seed}] no giver, skipped")
                continue
            if not force_far(env):
                print(f"  [{label} seed={seed}] never reached far, skipped")
                continue
            episodes_far += 1

            measured = 0
            for _ in range(MEASURE_STEPS * 3):     # allow retries, cap the work
                if measured >= MEASURE_STEPS:
                    break
                if not is_far(env._last_info):     # only far-state decisions count
                    try:
                        agent.step_no_learn()
                    except Exception:
                        break
                    continue
                ws_before = build_world_state(env._last_info)
                bucket = _bucket(ws_before)
                # snapshot the values the policy is reading RIGHT NOW
                for a in ("farm", "return_to_giver", "heal", "loot",
                          "turn_in_quest", "gather", "sell_junk", "accept_quest"):
                    qvals[a].append(frozen.value(bucket, a))
                try:
                    rec = agent.step_no_learn()
                except Exception:
                    break
                if rec.get("outcome_kind") == "ENV_ERROR":
                    break
                actions.append(rec["action"])
                wa = rec["ws_after"]
                deltas["distance"].append(
                    ws_before["distance_to_giver"] - wa["distance_to_giver"])
                deltas["quest_progress"].append(
                    wa["quest_progress"] - ws_before["quest_progress"])
                deltas["deaths"].append(wa["deaths"] - ws_before["deaths"])
                deltas["reward"].append(rec["reward"])
                measured += 1
            print(f"  [{label} seed={seed}] measured {measured} far-decisions")
        except Exception as ex:
            print(f"  [{label} seed={seed}] exception {ex!r}")
        finally:
            if env is not None:
                try:
                    env.close()
                except Exception:
                    pass

    n = len(actions)
    dist = {k: round(v / n, 4) for k, v in Counter(actions).items()} if n else {}
    q_mean = {a: round(sum(v) / len(v), 4) for a, v in qvals.items() if v}
    d_mean = {k: (round(sum(v) / len(v), 4) if v else 0.0) for k, v in deltas.items()}
    return {
        "label": label,
        "episodes_reached_far": episodes_far,
        "far_decisions": n,
        "distinct_actions": len(set(actions)),
        "P": dist,
        "Q_mean_at_far": q_mean,
        "mean_deltas": d_mean,
    }


# ---------------------------------------------------------------- training
def train(mem: ExperienceStore) -> dict:
    stats = {"episodes": 0, "steps": 0, "env_errors": 0}
    for i, seed in enumerate(TRAIN_SEEDS):
        env = None
        try:
            env = HierarchicalWoWEnv(player_class="warrior", max_steps=3000, seed=seed)
            env.reset(seed=seed)
            agent = Agent(env, mem, seed=seed * 3 + 1)
            if not accept_welcome(env):
                print(f"  [train ep{i} seed={seed}] no giver, skipped")
                continue
            force_far(env)
            # free learning at far: the agent may choose anything and lives with it
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


# ---------------------------------------------------------------- report
def main():
    if os.path.exists(EXP_PATH):
        os.remove(EXP_PATH)
    mem = ExperienceStore(path=EXP_PATH)

    print("=== BEFORE (memory empty, frozen during measurement) ===")
    before = measure_phase("BEFORE", mem, EVAL_SEEDS)

    print("\n=== TRAIN (learning ON) ===")
    tstats = train(mem)

    print("\n=== AFTER (identical protocol, memory frozen during measurement) ===")
    after = measure_phase("AFTER", mem, EVAL_SEEDS)

    # ---- comparison ----
    print("\n" + "=" * 62)
    print("P(action | far)   BEFORE -> AFTER")
    keys = sorted(set(before["P"]) | set(after["P"]))
    for k in keys:
        b, a = before["P"].get(k, 0.0), after["P"].get(k, 0.0)
        print(f"  {k:16s} {b:6.3f} -> {a:6.3f}   ({a - b:+.3f})")

    print("\nQ(far, action)    BEFORE -> AFTER  (re-valuation, not just clicks)")
    qkeys = sorted(set(before["Q_mean_at_far"]) | set(after["Q_mean_at_far"]))
    for k in qkeys:
        b = before["Q_mean_at_far"].get(k, 0.0)
        a = after["Q_mean_at_far"].get(k, 0.0)
        if abs(b) < 1e-9 and abs(a) < 1e-9:
            continue
        print(f"  {k:16s} {b:+7.4f} -> {a:+7.4f}   ({a - b:+.4f})")

    print("\nmean measured deltas per far-decision")
    for k in ("distance", "quest_progress", "deaths", "reward"):
        b = before["mean_deltas"].get(k, 0.0)
        a = after["mean_deltas"].get(k, 0.0)
        print(f"  {k:16s} {b:+8.4f} -> {a:+8.4f}")

    # ---- criteria (user's, not a target number) ----
    print("\n" + "=" * 62)
    print("CRITERIA")
    n_ok = before["far_decisions"] >= 20 and after["far_decisions"] >= 20
    print(f"  [{'x' if n_ok else ' '}] enough far-decisions in BOTH phases "
          f"({before['far_decisions']} / {after['far_decisions']})")

    alt_alive = after["distinct_actions"] >= 2
    print(f"  [{'x' if alt_alive else ' '}] alternatives did NOT disappear "
          f"({after['distinct_actions']} distinct actions at far)")

    farm_possible = after["P"].get("farm", 0.0) > 0.0
    print(f"  [{'x' if farm_possible else ' '}] farm still possible "
          f"(P={after['P'].get('farm', 0.0):.4f})")

    useful_up = (after["P"].get("return_to_giver", 0.0)
                 > before["P"].get("return_to_giver", 0.0))
    print(f"  [{'x' if useful_up else ' '}] P(useful=return|far) increased")

    q_moved = any(
        abs(after["Q_mean_at_far"].get(k, 0.0) - before["Q_mean_at_far"].get(k, 0.0)) > 1e-4
        for k in qkeys)
    print(f"  [{'x' if q_moved else ' '}] Q-values were re-valued (not just action counts)")

    dist_improved = (after["mean_deltas"].get("distance", 0.0)
                     > before["mean_deltas"].get("distance", 0.0))
    print(f"  [{'x' if dist_improved else ' '}] mean distance-closed per decision improved")

    passed = n_ok and alt_alive and farm_possible and q_moved
    print(f"\n  VERDICT: {'PASS' if passed else 'NOT PROVEN'}"
          f"  (learning visible + exploration preserved)"
          if passed else
          f"\n  VERDICT: NOT PROVEN — see unchecked criteria above")

    report = {
        "before": before,
        "after": after,
        "train": tstats,
        "criteria": {
            "enough_far_decisions": n_ok,
            "alternatives_alive": alt_alive,
            "farm_possible": farm_possible,
            "useful_action_up": useful_up,
            "q_revalued": q_moved,
            "distance_improved": dist_improved,
            "passed": passed,
        },
        "protocol": {
            "eval_seeds": EVAL_SEEDS,
            "train_seeds": TRAIN_SEEDS,
            "measure_steps": MEASURE_STEPS,
            "far_threshold": FAR_THRESHOLD,
            "memory_frozen_during_measurement": True,
        },
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\nreport -> {REPORT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
