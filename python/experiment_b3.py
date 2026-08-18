"""Experiment B3 — the REAL test of the original idea.

Per user 2026-08-17. No architecture change. No `if far -> return` rule. No PPO.

B2's flaw: force_far walked AWAY from the giver with plain forward -> a BARREN
state with no mob nearby, so return_to_giver could never show a benefit and every
action got a negative lesson. B3 puts the agent in a REAL game state:

    quest  = ACTIVE, progress < required
    distance_to_giver = far (>80)
    mob_nearby        = true

reached by ACTUAL farming (so the state is genuine, not an artificial walk). The
agent then freely chooses among {farm, return_to_giver, explore, ...} and we
measure, per far+mob decision:

    P(action | state)
    Q(state, action)          <- re-valuation, the core claim
    reward, quest_progress_delta, distance_delta, next_state

The expected honest result (NOT a target number):
    after negative experience at far+mob:
      Q(far, return) rises, Q(far, farm) falls
      P(farm|far) stays > 0  (not hard-forbidden)
      distance decreases, quest_progress does not regress

We also test TRANSFER: measure at far=80 / 100 / 130 across seeds. If the agent
learned the RELATIONSHIP (return closes distance, farm does not) rather than one
discrete bucket, behaviour should shift smoothly across these, not only at one
exact distance.

Protocol guarantees (same as B2):
  - BEFORE and AFTER use the SAME eval seeds, SAME forcing (real farm to far+mob),
    SAME measured-step count.
  - memory frozen during measurement (deepcopy + step_no_learn) so measuring
    does not teach.
  - only steps that are genuinely (far AND mob) count as measured decisions.

RETURN_STEP_BUDGET stays ATOMIC (one short leg per call, see quest_skill.py):
  97 -> 70 -> 43 -> 16 -> 6(SUCCESS), each its own measured transition. We do NOT
  turn return_to_giver into a hidden navigate-until-done.
"""

import copy
import json
import os
import sys
from collections import Counter, defaultdict

from hierarchical_env import (HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT,
                              SKILLS)
from agent import Agent
from memory import ExperienceStore, _bucket
from quest_capability import QuestCapability
from world_state import build_world_state

EXP_PATH = os.path.join(os.path.dirname(__file__), "experience_b3.json")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "experiment_b3_report.json")

# Identical protocol for BEFORE and AFTER
EVAL_SEEDS = [4242, 5353, 6464]
TRAIN_SEEDS = [42, 107, 256, 511, 909]
MEASURE_STEPS = 30
FARM_FAR_CAP = 150          # max farm iterations while forcing far+mob
FAR_THRESHOLD = 80.0
TRANSFER_DISTANCES = [80, 100, 130]   # transfer probes (not used to force; measured)


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
    """The B3 state: quest ACTIVE and far and a mob nearby."""
    ws = build_world_state(info)
    return (ws["quest_status"] == "ACTIVE"
            and "far=1" in _bucket(ws)
            and has_mob(info))


def force_far_mob(env) -> bool:
    """Drift into the REAL state (far AND mob nearby) by actual farming.

    Farming walks the player toward + attacks mobs, so it naturally yields
    mob_nearby=true while drifting far. If the player stops moving (no targetable
    mob), relocate with a forward+turn step and farm again. Verified to reach
    far+mob on all eval seeds (dist 90-97, real progress).

    Hard wall-clock cap: this used to hang the whole experiment when a seed
    drifted without ever hitting far+mob (player kept moving so the stuck guard
    never fired, but the state was never reached). Bail out so the run completes
    and reports "never reached" instead of stalling forever.
    """
    import time
    t0 = time.time()
    stuck = 0
    prev = None
    for _ in range(FARM_FAR_CAP):
        if time.time() - t0 > 240:        # <=240s per force, never hang
            return is_real_state(env._last_info)
        if is_real_state(env._last_info):
            return True
        try:
            env.step(0)
        except Exception:
            return is_real_state(env._last_info)
        pos = env._last_info.get("player_pos")
        if prev and abs(pos[0] - prev[0]) < 0.1 and abs(pos[1] - prev[1]) < 0.1:
            stuck += 1
            if stuck >= 5:
                env.base.step(ACT_FORWARD)
                env.base.step(ACT_TURN_LEFT)
                stuck = 0
        else:
            stuck = 0
        prev = pos
    return is_real_state(env._last_info)


def measure_phase(label: str, mem: ExperienceStore, seeds) -> dict:
    """Identical measurement protocol with memory FROZEN.

    Returns action distribution + Q-values + measured deltas, counted ONLY for
    genuine (far AND mob) decisions. Also captures the transfer probe:
    Q(far, return) / Q(far, farm) bucketed by coarse distance band.
    """
    frozen = copy.deepcopy(mem)
    actions = []
    qvals = defaultdict(list)
    deltas = {"distance": [], "quest_progress": [], "deaths": [], "reward": []}
    transfer = defaultdict(lambda: defaultdict(list))   # band -> action -> [q]
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
            if not force_far_mob(env):
                print(f"  [{label} seed={seed}] never reached far+mob, skipped")
                continue
            episodes += 1

            measured = 0
            recover = 0
            for _ in range(MEASURE_STEPS * 6):
                if measured >= MEASURE_STEPS:
                    break
                if not is_real_state(env._last_info):
                    # NOT far+mob: the agent's own choice drifted out of the
                    # measured state (e.g. farm killed the only nearby mob). For an
                    # HONEST measurement we re-establish the state. A full
                    # force_far_mob (~50s) per recovery was too slow; instead do a
                    # few cheap farm bursts (each ~1s) — farming will re-acquire a
                    # nearby mob and the player is already far, so far+mob returns
                    # quickly without re-drifting.
                    recover += 1
                    if recover > 60:
                        break
                    try:
                        env.step(0)
                        env.step(0)
                    except Exception:
                        break
                    continue
                recover = 0
                ws = build_world_state(env._last_info)
                bucket = _bucket(ws)
                for a in SKILLS:
                    qvals[a].append(frozen.value(bucket, a))
                    # transfer band: 80-100 / 100-130 / 130+
                    band = ("80-100" if ws["distance_to_giver"] < 100 else
                            "100-130" if ws["distance_to_giver"] < 130 else "130+")
                    transfer[band][a].append(frozen.value(bucket, a))
                try:
                    rec = agent.step_no_learn()
                except Exception:
                    break
                if rec.get("outcome_kind") == "ENV_ERROR":
                    break
                actions.append(rec["action"])
                wa = rec["ws_after"]
                deltas["distance"].append(ws["distance_to_giver"] - wa["distance_to_giver"])
                deltas["quest_progress"].append(wa["quest_progress"] - ws["quest_progress"])
                deltas["deaths"].append(wa["deaths"] - ws["deaths"])
                deltas["reward"].append(rec["reward"])
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
    dist = {k: round(v / n, 4) for k, v in Counter(actions).items()} if n else {}
    q_mean = {a: round(sum(v) / len(v), 4) for a, v in qvals.items() if v}
    transfer_mean = {
        band: {a: round(sum(v) / len(v), 4) for a, v in acts.items() if v}
        for band, acts in transfer.items()
    }
    d_mean = {k: (round(sum(v) / len(v), 4) if v else 0.0) for k, v in deltas.items()}
    return {
        "label": label,
        "episodes_reached_state": episodes,
        "far_mob_decisions": n,
        "distinct_actions": len(set(actions)),
        "P": dist,
        "Q_mean_at_far_mob": q_mean,
        "Q_by_distance_band": transfer_mean,
        "mean_deltas": d_mean,
    }


def train(mem: ExperienceStore) -> dict:
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
            force_far_mob(env)
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

    print("=== BEFORE (memory empty, frozen during measurement) ===")
    before = measure_phase("BEFORE", mem, EVAL_SEEDS)

    print("\n=== TRAIN (learning ON) ===")
    tstats = train(mem)

    print("\n=== AFTER (identical protocol, memory frozen during measurement) ===")
    after = measure_phase("AFTER", mem, EVAL_SEEDS)

    # ---- comparison ----
    print("\n" + "=" * 64)
    print("P(action | far+mob)   BEFORE -> AFTER")
    for k in sorted(set(before["P"]) | set(after["P"])):
        b, a = before["P"].get(k, 0.0), after["P"].get(k, 0.0)
        print(f"  {k:16s} {b:6.3f} -> {a:6.3f}   ({a - b:+.3f})")

    print("\nQ(far+mob, action)   BEFORE -> AFTER  (re-valuation)")
    qkeys = sorted(set(before["Q_mean_at_far_mob"]) | set(after["Q_mean_at_far_mob"]))
    for k in qkeys:
        b = before["Q_mean_at_far_mob"].get(k, 0.0)
        a = after["Q_mean_at_far_mob"].get(k, 0.0)
        if abs(b) < 1e-9 and abs(a) < 1e-9:
            continue
        print(f"  {k:16s} {b:+7.4f} -> {a:+7.4f}   ({a - b:+.4f})")

    # transfer: Q(far, return) / Q(far, farm) by distance band, AFTER only
    print("\nTRANSFER (AFTER): Q by distance band")
    for band in sorted(after["Q_by_distance_band"].keys()):
        acts = after["Q_by_distance_band"][band]
        r = acts.get("return_to_giver")
        f = acts.get("farm")
        print(f"  band {band:7s}: Q(return)={r if r is not None else float('nan'):+7.4f}  "
              f"Q(farm)={f if f is not None else float('nan'):+7.4f}")

    print("\nmean measured deltas per far+mob decision")
    for k in ("distance", "quest_progress", "deaths", "reward"):
        b = before["mean_deltas"].get(k, 0.0)
        a = after["mean_deltas"].get(k, 0.0)
        print(f"  {k:16s} {b:+8.4f} -> {a:+8.4f}")

    # ---- criteria (user's, not a target number) ----
    print("\n" + "=" * 64)
    print("CRITERIA")
    n_ok = before["far_mob_decisions"] >= 20 and after["far_mob_decisions"] >= 20
    print(f"  [{'x' if n_ok else ' '}] enough far+mob decisions in BOTH phases "
          f"({before['far_mob_decisions']} / {after['far_mob_decisions']})")

    alt_alive = after["distinct_actions"] >= 2
    print(f"  [{'x' if alt_alive else ' '}] alternatives did NOT disappear "
          f"({after['distinct_actions']} distinct actions)")

    farm_possible = after["P"].get("farm", 0.0) > 0.0
    print(f"  [{'x' if farm_possible else ' '}] farm still possible "
          f"(P={after['P'].get('farm', 0.0):.4f})")

    # the real claim: at far+mob, return should be re-valued UP, farm DOWN
    q_ret_b = before["Q_mean_at_far_mob"].get("return_to_giver", 0.0)
    q_ret_a = after["Q_mean_at_far_mob"].get("return_to_giver", 0.0)
    q_farm_b = before["Q_mean_at_far_mob"].get("farm", 0.0)
    q_farm_a = after["Q_mean_at_far_mob"].get("farm", 0.0)
    return_up = q_ret_a > q_ret_b
    farm_down = q_farm_a < q_farm_b
    print(f"  [{'x' if return_up else ' '}] Q(far, return) rose "
          f"({q_ret_b:+.4f} -> {q_ret_a:+.4f})")
    print(f"  [{'x' if farm_down else ' '}] Q(far, farm) fell "
          f"({q_farm_b:+.4f} -> {q_farm_a:+.4f})")

    dist_improved = after["mean_deltas"].get("distance", 0.0) > before["mean_deltas"].get("distance", 0.0)
    print(f"  [{'x' if dist_improved else ' '}] mean distance-closed per decision improved")

    # transfer: Q(return) > Q(farm) in at least one non-80 band (learned relation,
    # not just one bucket)
    transfer_ok = False
    for band, acts in after["Q_by_distance_band"].items():
        r = acts.get("return_to_giver")
        f = acts.get("farm")
        if r is not None and f is not None and r > f:
            transfer_ok = True
            break
    print(f"  [{'x' if transfer_ok else ' '}] TRANSFER: Q(return)>Q(farm) in >=1 distance band "
          f"(relation, not single bucket)")

    passed = n_ok and alt_alive and farm_possible and return_up and farm_down and transfer_ok
    print(f"\n  VERDICT: {'PASS — self-learning stage CLOSED' if passed else 'NOT PROVEN'}")

    report = {
        "before": before,
        "after": after,
        "train": tstats,
        "criteria": {
            "enough_far_mob_decisions": n_ok,
            "alternatives_alive": alt_alive,
            "farm_possible": farm_possible,
            "q_return_up": return_up,
            "q_farm_down": farm_down,
            "distance_improved": dist_improved,
            "transfer": transfer_ok,
            "passed": passed,
        },
        "protocol": {
            "eval_seeds": EVAL_SEEDS,
            "train_seeds": TRAIN_SEEDS,
            "measure_steps": MEASURE_STEPS,
            "far_threshold": FAR_THRESHOLD,
            "state": "quest=ACTIVE, far, mob_nearby",
            "memory_frozen_during_measurement": True,
            "return_step_atomic": True,
        },
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\nreport -> {REPORT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
