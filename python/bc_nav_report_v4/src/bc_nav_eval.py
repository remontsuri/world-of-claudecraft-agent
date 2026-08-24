"""Closed-loop BC navigation evaluation (NO PPO, NO Sim changes).

Loads bc_nav_A.pt or bc_nav_B.pt and rolls it out in the SAME env PPO used
(CurriculumEnv stage=3). Reports the user-required metrics per seed and the
FIRST_DIVERGENCE vs the Oracle state-machine:

  SEARCH -> NAV -> target_nearest -> target_has -> APPROACH -> attack
  -> damage -> kill

Also prints a per-step divergence snippet when BC first violates the expected
next state, e.g. "mob visible but BC chose ability_17 instead of turn".

Run:
  therock-test/Scripts/python.exe bc_nav_eval.py --model A --seeds 42 43 ... 51
  therock-test/Scripts/python.exe bc_nav_eval.py --model B --seeds 42 43 ... 51
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
_WOC = Path(r"D:/world-of-claudecraft/python")
if str(_WOC) not in sys.path:
    sys.path.insert(0, str(_WOC))
_WLLM = Path(r"D:/woc-llm")
if str(_WLLM) not in sys.path:
    sys.path.insert(0, str(_WLLM))

import numpy as np
import torch
import torch.nn as nn

import audit_common as ac
import curriculum_env as ce
import nav_features as nf

ROOT = Path(__file__).resolve().parent
OUT_A = ROOT / "nav_data" / "bc_nav_A.pt"
OUT_B = ROOT / "nav_data" / "bc_nav_B.pt"

FEAT_KEYS = ["mob_sin", "mob_cos", "turn_dir", "turn_strength",
             "forward_ok", "target_has", "target_dist", "in_combat_range"]
ABILITY_SLOTS = (ac.TGT - 16) // 2  # 48


class BCPolicy(nn.Module):
    def __init__(self, obs_dim, n_act):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, 512), nn.ReLU(),
            nn.Linear(512, 256), nn.ReLU(),
            nn.Linear(256, 128), nn.ReLU(),
            nn.Linear(128, n_act),
        )

    def forward(self, x):
        return self.net(x)


def correct_turn(act, mob_sin, aid):
    """Oracle-expected turn vs BC action. None if straight phase.
    KEPT ONLY for reference; replaced by heading_err as primary metric."""
    if abs(mob_sin) <= 0.15:
        return None
    want_left = mob_sin > 0
    if act not in (aid["turn_left"], aid["turn_right"]):
        return False
    return (act == aid["turn_left"]) == want_left


def heading_err_deg(act, mob_sin, aid):
    """Heading error to mob, independent of literal Oracle-turn match.

    Agent's intended heading per action:
      forward      -> 0 deg (straight ahead)
      turn_left    -> +90 deg (left of facing)
      turn_right   -> -90 deg (right of facing)
    Mob bearing per obs: asin(clamp(mob_sin,-1,1)) in [-90,90] deg
      (+ = mob on left, - = mob on right).

    Returns abs(angle between agent heading and mob bearing) in degrees.
    0 = agent heading exactly at the mob. Lower is better. None if no mob.
    NOTE: pure 'forward' when mob is at +90 (far left) scores 90 deg error —
    this is the HONEST metric: it measures whether the agent points at the mob,
    not whether it copied Oracle's exact step."""
    if mob_sin is None:
        return None
    mob_bearing = np.degrees(np.arcsin(float(np.clip(mob_sin, -1.0, 1.0))))
    if act == aid["forward"]:
        agent_heading = 0.0
    elif act == aid["turn_left"]:
        agent_heading = 90.0
    elif act == aid["turn_right"]:
        agent_heading = -90.0
    else:
        return None  # non-nav action: not scored for heading
    return abs(agent_heading - mob_bearing)


def first_divergence(state, act, mob_sin, aid):
    """Return Oracle state-machine stage name where BC first breaks the chain.
    state: one of SEARCH/NAV/ACQUIRE/APPROACH/COMBAT/DEAD.
    NAV is checked FIRST so navigation divergence is never masked by later
    phases reaching combat radius."""
    if state == "NAV" and act not in (aid["turn_left"], aid["turn_right"],
                                       aid["target_nearest"]):
        return "NAV"
    if state == "ACQUIRE" and act not in (aid["forward"], aid["target_nearest"]):
        return "ACQUIRE"
    if state == "APPROACH" and act not in (aid["turn_left"], aid["turn_right"],
                                            aid["forward"]):
        return "APPROACH"
    if state == "COMBAT" and act != aid["attack"]:
        return "COMBAT"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["A", "B"], required=True)
    ap.add_argument("--seeds", nargs="+", type=int,
                    default=[42, 43, 44, 45, 46, 47, 48, 49, 50, 51])
    args = ap.parse_args()

    # Safe: our own .pt contains only state_dict + int/floats (weights_only=True).
    ckpt = torch.load(OUT_B if args.model == "B" else OUT_A,
                     map_location="cpu", weights_only=True)
    model = BCPolicy(ckpt["obs_dim"], ckpt["n_act"])
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    aid = None
    results = []
    # global tick-level accumulators for chi-square (attack vs not, A vs B)
    atk_close_total = 0
    close_total = 0
    dead_total = 0
    tgt_sw_total = 0
    print(f"{'model':6s} {'seed':>4s} {'atk<5%':>6s} {'head°':>6s} {'fwd%':>6s} "
          f"{'tn%':>6s} {'th%':>6s} {'atk%':>6s} | {'minD':>5s} {'dmg':>5s} "
          f"{'kills':>5s} {'dead':>4s} {'tSw':>4s} | {'1st_div':>10s}")
    for seed in args.seeds:
        env = ce.CurriculumEnv(stage=3, player_class="warrior",
                               max_steps=400, frame_skip=5)
        obs, info = env.reset(seed=seed)
        if aid is None:
            aid = ac.make_aid(env.action_names)
        actions = []
        saw = turn_ok = turn_n = fwd = tn = th = atk = 0
        min_d = None
        head_err_sum = 0.0
        head_err_n = 0
        atk_close = 0          # attack actions while mob/target within MELEE-ish
        close_n = 0            # ticks with mob/target within MELEE-ish range
        tgt_switches = 0       # target_has 0<->1 transitions (target loss/reacquire)
        prev_th = 0
        dead = 0
        last = {"dmg": 0, "kills": 0}
        div = None
        div_step = None
        tracker = nf.CombatRangeTracker()
        for i in range(1, 401):
            target0, mob0 = nf.decode_nav_obs(obs, ABILITY_SLOTS)
            icr_now = tracker.update(bool(target0["has"]), target0["dist"])
            with torch.no_grad():
                if args.model == "B":
                    target, mob = nf.decode_nav_obs(obs, ABILITY_SLOTS)
                    if mob is not None:
                        nfobj = nf.make_nav_features(
                            mob_dist=mob["dist"], mob_sin=mob["sin"],
                            mob_cos=mob["cos"], target_has=bool(target["has"]),
                            target_dist=target["dist"], target_sin=target["sin"],
                            target_cos=target["cos"], in_combat_range=icr_now)
                    else:
                        nfobj = nf.make_nav_features(
                            mob_dist=nf.MOB_SAT * nf.DIST_SCALE, mob_sin=0.0,
                            mob_cos=0.0, target_has=bool(target["has"]),
                            target_dist=target["dist"], target_sin=target["sin"],
                            target_cos=target["cos"], in_combat_range=icr_now)
                    feats = np.asarray(
                        [[float(getattr(nfobj, k)) for k in FEAT_KEYS]],
                        dtype=np.float32)
                    xin = torch.from_numpy(
                        np.concatenate([np.asarray(obs, np.float32)[None],
                                       feats], axis=1)).to(device)
                else:
                    xin = torch.from_numpy(
                        np.asarray(obs, np.float32)[None]).to(device)
                act = int(model(xin).argmax(1).item())
            nxt, r, term, trunc, info = env.step(act)
            p, target, mob = ac.decode(obs)
            actions.append(act)
            state = nf.make_nav_features(
                mob_dist=(mob["dist"] if mob else nf.MOB_SAT * nf.DIST_SCALE),
                mob_sin=(mob["sin"] if mob else 0.0),
                mob_cos=(mob["cos"] if mob else 0.0),
                target_has=bool(target["has"]),
                target_dist=target["dist"],
                target_sin=target["sin"], target_cos=target["cos"]).phase
            ms = mob["sin"] if mob else None
            if (mob is not None) or target["has"]:
                saw += 1
                if ms is not None:
                    he = heading_err_deg(act, ms, aid)
                    if he is not None:
                        head_err_sum += he
                        head_err_n += 1
            if mob is not None:
                if min_d is None or mob["dist"] < min_d:
                    min_d = mob["dist"]
                if mob["dist"] < 5.0:
                    close_n += 1
                    if act == aid["attack"]:
                        atk_close += 1
            elif target["has"]:
                if min_d is None or target["dist"] < min_d:
                    min_d = target["dist"]
                if target["dist"] < 5.0:
                    close_n += 1
                    if act == aid["attack"]:
                        atk_close += 1
            if act == aid["forward"]:
                fwd += 1
            if act == aid["target_nearest"]:
                tn += 1
            if target["has"]:
                th += 1
            if act == aid["attack"]:
                atk += 1
            # target loss / reacquire tracking
            cur_th = 1 if target["has"] else 0
            if prev_th != cur_th:
                tgt_switches += 1
                prev_th = cur_th
            dmg = info.get("damageDealt", 0) or 0
            kills = info.get("kills", 0) or 0
            deaths = info.get("deaths", 0) or 0
            if deaths > 0 or p["dead"]:
                dead = 1
            if div is None:
                d = first_divergence(state, act, ms if mob else 0.0, aid)
                if d:
                    div = d
                    div_step = i
            last = {"dmg": dmg, "kills": kills}
            obs = nxt
            if term or trunc:
                break
        env.close()
        total = len(actions)
        c = lambda x: (x / total * 100 if total else 0.0)
        head_err = (head_err_sum / head_err_n) if head_err_n else float("nan")
        atk_close_pct = (atk_close / close_n * 100) if close_n else float("nan")
        print(f"{args.model:6s} {seed:>4d} {atk_close_pct:>6.1f} {head_err:>6.1f} "
              f"{c(fwd):>6.1f} {c(tn):>6.1f} {c(th):>6.1f} {c(atk):>6.1f} | "
              f"{(min_d if min_d is not None else -1):>5.1f} {last['dmg']:>5.0f} "
              f"{last['kills']:>5d} {dead} {tgt_switches:>3d} | {str(div):>10s}@{div_step}")
        results.append((last["kills"], c(tn), c(fwd), head_err,
                        min_d if min_d else -1, last["dmg"], div, atk_close_pct,
                        dead, tgt_switches))
        # accumulate globals for chi-square (tick-level: attack vs not within range)
        atk_close_total += atk_close
        close_total += close_n
        dead_total += dead
        tgt_sw_total += tgt_switches

    kills = sum(r[0] for r in results)
    tn = np.mean([r[1] for r in results])
    fwd = np.mean([r[2] for r in results])
    head = np.nanmean([r[3] for r in results])
    mind = np.mean([r[4] for r in results])
    dmg = np.mean([r[5] for r in results])
    atk_close = np.nanmean([r[7] for r in results])
    divs = [r[6] for r in results if r[6]]
    fd = max(set(divs), key=divs.count) if divs else "none"
    dead_rate = dead_total / len(results) * 100 if results else 0.0
    tsw_mean = tgt_sw_total / len(results) if results else 0.0
    print(f"\n=== {args.model} SUMMARY ===")
    print(f"kills/10      = {kills}/10")
    print(f"tn%           = {tn:.1f}")
    print(f"forward%      = {fwd:.1f}")
    print(f"heading_err°  = {head:.1f}  (mean abs angle between agent heading and mob; LOWER=better)")
    print(f"atk%<5yd      = {atk_close:.1f}  (attack-action rate while mob/target within 5yd)")
    print(f"minD         = {mind:.1f}")
    print(f"damage        = {dmg:.0f}")
    print(f"death_rate   = {dead_rate:.0f}%  (episodes where player died)")
    print(f"tgt_switches  = {tsw_mean:.1f}  (target_has 0<->1 per episode; higher = loses target more)")
    print(f"first_divergence (most common) = {fd}")
    print(f"GATE >=8/10: {kills >= 8}")
    print(f"\nNOTE: this is a BC-only A/B (raw obs vs obs+nav-features). PPO was NOT"
          f"tested here. The 'PPO has the same problem' claim comes from the earlier"
          f"trajectory_audit (nav_fwd divergence), not from this script.")
    # dump global tick-level counts for cross-model chi-square
    import json
    counts_path = ROOT / "nav_data" / f"bc_nav_{args.model}_counts.json"
    with open(counts_path, "w") as f:
        json.dump({"atk_close": int(atk_close_total),
                   "close": int(close_total)}, f)
    print(f"[counts saved] {counts_path}  atk_close={atk_close_total} close={close_total}")


if __name__ == "__main__":
    main()
