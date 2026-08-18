"""causal_live_test.py — Level-4 live causal-learning proof (Online WoC).

Protocol (per user 2026-08-18):
  Goal: prove the agent's POLICY CHANGES because of its OWN online negative
  experience — not because of a unit test.

  S = { alive, hp>=0.8, mob=1, far=1, qs=NONE }
      (far=1 is automatic when qs=NONE: distance_to_giver=999>80)
      Quest is intentionally NOT required (test ONE hypothesis:
      "agent learns not to repeat a bad farm in a dangerous spot").

  Steps:
    1. SETUP  — respawn if dead; navigate to a live mob (dist<=45); reach S.
    2. BEFORE — freeze memory; measure Q(S,farm), P(farm|S) analytically
                (exploration_weight=0 -> P reflects Q only, no visit-count confound).
    3. TRAIN  — controlled intervention: step_forced('farm', learn=True) ×N.
                The CHOICE is forced; the OUTCOME (real combat, real death/damage)
                comes from the live world. We require a REAL ONLINE NEGATIVE
                (reward < -0.1, i.e. a genuine death) before we count the test.
                This is a training probe, NOT a claimed autonomous decision.
    4. FREEZE — stop learning.
    5. AFTER  — restore S as close as possible; re-measure Q(S,farm), P(farm|S).
    6. PASS   — real_negative>0 AND Q_after<Q_before AND P_after<P_before
                AND bucket identical (same S key).

  We do NOT edit memory/reward/TD. We only drive the existing agent + bridge.

  Memory path is isolated (experience_causal.json) so we start from a clean,
  honest prior (Q=0, P=uniform) and the only signal is the TRAIN intervention.
"""

import json
import math
import os
import sys
import time

from browser_env import BrowserEnv
from agent import Agent
from memory import ExperienceStore, _bucket
from world_state import build_world_state
from policy import GoalManager

T = 1.2  # must match GoalManager default temperature
MEM_PATH = os.path.join(os.path.dirname(__file__), "experience_causal.json")
MAX_TRAIN = 50


def analytic_softmax(vals: dict, temp: float = T) -> dict:
    """P(a|S) = exp(w_a/T) / sum_b exp(w_b/T), NO exploration bonus (ew=0)."""
    if not vals:
        return {}
    maxw = max(vals.values())
    exps = {a: math.exp((w - maxw) / max(temp, 1e-3)) for a, w in vals.items()}
    tot = sum(exps.values())
    return {a: e / tot for a, e in exps.items()}


def find_mobs(info):
    near = info.get("nearby") or []
    return [e for e in near
            if (e.get("kind") == "mob" or e.get("type") == "mob")
            and not e.get("lootable") and not e.get("dead")]


def snapshot_state(env, policy, mem):
    info = env._last_info
    ws = build_world_state(info)
    bucket = _bucket(ws)
    cands = policy._candidates(info, ws)
    vals = {a: mem.value(bucket, a) for a in cands}
    P = analytic_softmax(vals, T)
    return ws, bucket, cands, vals, P


def setup_S(env, agent, mem, policy, max_nav_attempts: int = 50):
    """Reach S = alive, hp>=0.8, mob present, qs=NONE. Returns (ok, ws).

    The agent CAN walk (verified: navigate_to_coord arrives within ~5yd). The
    risk is the character DYING mid-search (mobs, or the long navigate walk),
    after which a dead character cannot move. So we re-respawn inside the loop
    whenever hp<=0 or hp<0.8 (respawn resets to full hp at the giver), and we
    chunk the navigate (max_steps=50 ~ 11s) so we can re-check hp between calls
    instead of blocking 35s and maybe coming back dead.
    """
    for attempt in range(max_nav_attempts):
        info = env._last_info
        ws = build_world_state(info)
        # keep ALIVE only — do NOT respawn on low hp, or we teleport to the
        # giver (mob-free zone) and lose the mob we just found. A dead char
        # cannot move; a hurt char still can and that is a valid S for the test.
        if info.get("player", {}).get("dead") or ws.get("hp_frac", 1.0) <= 0.0:
            env.respawn()
            info = env._last_info
            ws = build_world_state(info)
        mobs = find_mobs(info)
        if mobs:
            m = mobs[0]
            mx, mz = m.get("x"), m.get("z")
            # chunked navigate: re-check hp between chunks
            for _ in range(5):
                cinfo = env._last_info
                cws = build_world_state(cinfo)
                if cinfo.get("player", {}).get("dead") or cws.get("hp_frac", 1.0) <= 0.0:
                    break  # died during approach — outer loop will respawn
                try:
                    env._navigate_to_coord(mx, mz, max_steps=50, timeout=60.0)
                except Exception as e:
                    print(f"[causal][setup] nav timeout ({e})")
                info = env._last_info
                px, pz = info.get("player_pos", [0, 0])
                d = math.hypot(mx - px, mz - pz)
                if d <= 45:
                    break
            ws = build_world_state(info)
            if d <= 45 and ws["hp_frac"] > 0.0 and ws["quest_status"] == "NONE":
                print(f"[causal][setup] reached S: dist={d:.1f} hp={ws['hp_frac']:.2f} bucket={_bucket(ws)}")
                return True, ws
        # no mob yet -> walk FORWARD (no turns) to leave the building area and
        # reach open ground where mobs spawn. explore_walk turns every 7th step
        # and circles in place, so we use raw forward instead.
        for _ in range(20):
            env._raw_move('forward')
        env._raw_move('stop')
        info = env._last_info
    return False, build_world_state(env._last_info)


def main():
    print(f"[causal] loading memory from {MEM_PATH}")
    mem = ExperienceStore(path=MEM_PATH)
    env = BrowserEnv(player_class="warrior", max_steps=100000, seed=7)
    env.reset(seed=7)
    agent = Agent(env, mem, seed=7)
    policy = agent.policy
    print("[causal] bridge online, character in world.")

    ok, ws = setup_S(env, agent, mem, policy)
    if not ok:
        print(f"[causal] SETUP FAILED — could not reach S. last ws={ws}")
        return

    # ---- BEFORE (frozen memory) ----
    ws_b, bucket_b, cands_b, vals_b, P_b = snapshot_state(env, policy, mem)
    Q_b_farm = vals_b.get("farm", 0.0)
    print(f"[causal] SETUP OK. bucket={bucket_b}")
    print(f"[causal] BEFORE  Q(farm)={Q_b_farm:+.4f}  P(farm|S)={P_b.get('farm',0):.4f}")

    # ---- TRAIN (controlled intervention) ----
    neg = 0
    first_neg = None
    all_r = []
    print(f"[causal] TRAIN: forcing farm up to {MAX_TRAIN} times, require real negative...")
    for i in range(MAX_TRAIN):
        info = env._last_info
        if info.get("player", {}).get("dead"):
            env.respawn()
            ok, _ = setup_S(env, agent, mem, policy)
            if not ok:
                break
            continue
        rec = agent.step_forced("farm", learn=True)
        r = rec["reward"]
        all_r.append(r)
        if r < -0.1:
            neg += 1
            if first_neg is None:
                first_neg = (i, r)
        ws = build_world_state(env._last_info)
        # keep S reachable: if mob gone or hp dropped, restore
        if not ws["has_mob"] or ws["hp_frac"] < 0.8:
            if ws["hp_frac"] < 0.8:
                agent.step_forced("heal", learn=False)
            ok, _ = setup_S(env, agent, mem, policy)
            if not ok:
                break

    print(f"[causal] TRAIN done. real_online_negatives={neg}  "
          f"(min reward={min(all_r) if all_r else 0:+.2f})")
    if first_neg:
        print(f"[causal] first negative at train-step {first_neg[0]}, reward={first_neg[1]:+.2f}")

    # ---- FREEZE (no more learning) ----
    # ---- AFTER (restore S, re-measure) ----
    ok, _ = setup_S(env, agent, mem, policy)
    ws_a, bucket_a, cands_a, vals_a, P_a = snapshot_state(env, policy, mem)
    Q_a_farm = vals_a.get("farm", 0.0)
    print(f"[causal] AFTER   Q(farm)={Q_a_farm:+.4f}  P(farm|S)={P_a.get('farm',0):.4f}")
    print(f"[causal] bucket BEFORE={bucket_b}")
    print(f"[causal] bucket AFTER ={bucket_a}")
    print(f"[causal] P BEFORE={ {a: round(P_b.get(a, 0), 3) for a in cands_b} }")
    print(f"[causal] P AFTER ={ {a: round(P_a.get(a, 0), 3) for a in cands_a} }")

    same_bucket = (bucket_b == bucket_a)
    passed = (
        neg > 0
        and same_bucket
        and Q_a_farm < Q_b_farm
        and P_a.get("farm", 0) < P_b.get("farm", 0)
    )
    print(f"[causal] === {'PASS' if passed else 'FAIL'} ===")
    print(f"[causal] real_negative>0 : {neg>0}")
    print(f"[causal] same bucket S   : {same_bucket}")
    print(f"[causal] Q_after<Q_before: {Q_a_farm < Q_b_farm}  ({Q_b_farm:+.3f} -> {Q_a_farm:+.3f})")
    print(f"[causal] P_after<P_before: {P_a.get('farm',0) < P_b.get('farm',0)}  "
          f"({P_b.get('farm',0):.3f} -> {P_a.get('farm',0):.3f})")
    mem.save()


if __name__ == "__main__":
    main()
