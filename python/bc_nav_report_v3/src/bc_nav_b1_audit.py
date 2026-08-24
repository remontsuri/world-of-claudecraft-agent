"""STEP 1 + STEP 2 (user plan): B1 closed-loop validation + B1-vs-Oracle audit.

NO training, NO DAgger, NO PPO. Loads the FROZEN bc_nav_B1.pt (ablation result,
+in_combat_range latch only) and runs fully closed-loop on FRESH seeds outside
the train/agg range (66-95). Also dumps B1 vs Oracle action traces on a few seeds
to locate the FIRST real divergence.

Metrics per episode (STEP 1):
  kills, episodes_with_kill, deaths, death_rate, atk%<5yd,
  target_switches, time_to_first_damage (steps), time_to_kill (steps),
  steps_in_combat_range, combat_range_exits_after_fight_start,
  max_turn_forward_loop

STEP 2: for AUDIT_SEEDS, print step | phase | B1_act | Oracle_act until first
divergence in APPROACH/COMBAT (NAV checked first so nav never masks later phases).

Run:
  therock-test/Scripts/python.exe bc_nav_b1_audit.py
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
OUT = ROOT / "nav_data" / "bc_nav_B1.pt"
FRESH_SEEDS = list(range(66, 96))        # 30 fresh seeds, outside train(42-61)/agg(42-65)
AUDIT_SEEDS = [66, 67, 68, 69, 70]       # detailed trace dump
ABILITY_SLOTS = (ac.TGT - 16) // 2
FEAT_KEYS = ["in_combat_range"]


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


def act_name(aid, a):
    inv = {v: k for k, v in aid.items()}
    return inv.get(a, str(a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", nargs="+", type=int, default=FRESH_SEEDS)
    args = ap.parse_args()

    ckpt = torch.load(OUT, map_location="cpu", weights_only=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = BCPolicy(ckpt["obs_dim"], ckpt["n_act"])
    model.load_state_dict(ckpt["state_dict"])
    model.to(device)
    model.eval()

    aid = ac.make_aid(ce.CurriculumEnv(stage=3, player_class="warrior",
                                       max_steps=1, frame_skip=5).action_names)

    def run_episode(seed, dump=False):
        env = ce.CurriculumEnv(stage=3, player_class="warrior",
                               max_steps=400, frame_skip=5)
        obs, _ = env.reset(seed=seed)
        tracker = nf.CombatRangeTracker()
        prev_or = {}
        fight_started = False
        first_dmg_step = None
        first_kill_step = None
        combat_steps = 0
        combat_exits = 0
        prev_icr = False
        tgt_sw = 0
        prev_th = 0
        max_loop = cur_loop = 0
        atk_close = close_n = 0
        min_d = None
        fwd = tn = th = atk = 0
        trace = []
        for step in range(1, 401):
            target, mob = nf.decode_nav_obs(obs, ABILITY_SLOTS)
            icr = tracker.update(bool(target["has"]), target["dist"])
            nfobj = nf.make_nav_features(
                mob_dist=(mob["dist"] if mob else nf.MOB_SAT * nf.DIST_SCALE),
                mob_sin=(mob["sin"] if mob else 0.0),
                mob_cos=(mob["cos"] if mob else 0.0),
                target_has=bool(target["has"]), target_dist=target["dist"],
                target_sin=target["sin"], target_cos=target["cos"],
                in_combat_range=icr)
            feats = np.asarray(
                [[float(icr if k == "in_combat_range" else getattr(nfobj, k))
                  for k in FEAT_KEYS]], dtype=np.float32)
            xin = torch.from_numpy(
                np.concatenate([np.asarray(obs, np.float32)[None], feats],
                               axis=1)).to(device)
            with torch.no_grad():
                b1_act = int(model(xin).argmax(1).item())
            or_act = int(ac.oracle_action(obs, aid, prev_or))
            nxt, r, term, trunc, info = env.step(b1_act)

            p, tgt, mb = ac.decode(obs)
            phase = nfobj.phase
            # divergence detection (NAV first, then APPROACH/COMBAT)
            div = None
            if phase == "NAV" and b1_act not in (aid["turn_left"], aid["turn_right"], aid["target_nearest"]):
                div = "NAV"
            elif phase == "ACQUIRE" and b1_act not in (aid["forward"], aid["target_nearest"]):
                div = "ACQUIRE"
            elif phase == "APPROACH" and b1_act not in (aid["turn_left"], aid["turn_right"], aid["forward"]):
                div = "APPROACH"
            elif phase == "COMBAT" and b1_act != aid["attack"]:
                div = "COMBAT"
            if dump and (len(trace) < 60):
                trace.append((step, phase, act_name(aid, b1_act),
                              act_name(aid, or_act), div))
            if dump and div and len([t for t in trace if t[4]]) == 0:
                pass  # keep going to show context

            # metrics
            if icr:
                combat_steps += 1
            if prev_icr and not icr and fight_started:
                combat_exits += 1
            prev_icr = icr
            if b1_act == aid["attack"]:
                fight_started = True
            if mb is not None:
                if min_d is None or mb["dist"] < min_d:
                    min_d = mb["dist"]
                if mb["dist"] < 5.0:
                    close_n += 1
                    if b1_act == aid["attack"]:
                        atk_close += 1
            elif tgt["has"]:
                if min_d is None or tgt["dist"] < min_d:
                    min_d = tgt["dist"]
                if tgt["dist"] < 5.0:
                    close_n += 1
                    if b1_act == aid["attack"]:
                        atk_close += 1
            if b1_act == aid["forward"]:
                fwd += 1
            if b1_act == aid["target_nearest"]:
                tn += 1
            if tgt["has"]:
                th += 1
            if b1_act == aid["attack"]:
                atk += 1
            if b1_act in (aid["turn_left"], aid["turn_right"], aid["forward"]) \
                    and b1_act not in (aid["attack"], aid["target_nearest"]):
                cur_loop += 1
                max_loop = max(max_loop, cur_loop)
            else:
                cur_loop = 0
            cur_th = 1 if tgt["has"] else 0
            if prev_th != cur_th:
                tgt_sw += 1
                prev_th = cur_th
            dmg = info.get("damageDealt", 0) or 0
            kills = info.get("kills", 0) or 0
            deaths = info.get("deaths", 0) or 0
            if dmg > 0 and first_dmg_step is None:
                first_dmg_step = step
            if kills > 0 and first_kill_step is None:
                first_kill_step = step
            dead = 1 if (deaths > 0 or p["dead"]) else 0
            obs = nxt
            if term or trunc:
                break
        env.close()
        total = sum(1 for _ in range(1))  # placeholder
        n_steps = step
        atk_pct = (atk_close / close_n * 100) if close_n else float("nan")
        return {
            "seed": seed, "kills": kills, "eWkill": int(kills > 0),
            "dead": dead, "dmg": dmg, "atk_pct": atk_pct,
            "min_d": min_d if min_d else -1, "tgt_sw": tgt_sw,
            "first_dmg": first_dmg_step or -1, "first_kill": first_kill_step or -1,
            "combat_steps": combat_steps, "combat_exits": combat_exits,
            "max_loop": max_loop, "n": n_steps,
            "fwd": fwd, "tn": tn, "th": th, "atk": atk,
            "trace": trace,
        }

    # STEP 1: all fresh seeds
    print(f"=== STEP 1: B1 closed-loop, {len(args.seeds)} fresh seeds ===")
    rows = [run_episode(s) for s in args.seeds]
    n = len(rows)
    eWkill = sum(r["eWkill"] for r in rows)
    deaths = sum(r["dead"] for r in rows)
    dmg = np.mean([r["dmg"] for r in rows])
    atk_pct = np.nanmean([r["atk_pct"] for r in rows])
    tsw = np.mean([r["tgt_sw"] for r in rows])
    ftd = np.mean([r["first_dmg"] for r in rows if r["first_dmg"] > 0])
    ftk = np.mean([r["first_kill"] for r in rows if r["first_kill"] > 0])
    cs = np.mean([r["combat_steps"] for r in rows])
    ce_ = np.mean([r["combat_exits"] for r in rows])
    ml = np.mean([r["max_loop"] for r in rows])
    print(f"episodes_with_kill = {eWkill}/{n}  ({eWkill/n*100:.0f}%)")
    print(f"death_rate         = {deaths/n*100:.0f}%  ({deaths}/{n})")
    print(f"mean damage        = {dmg:.0f}")
    print(f"atk%<5yd           = {atk_pct:.1f}")
    print(f"mean target_sw     = {tsw:.1f}")
    print(f"mean time_to_dmg   = {ftd:.0f} steps")
    print(f"mean time_to_kill  = {ftk:.0f} steps")
    print(f"mean combat_steps  = {cs:.0f}")
    print(f"mean combat_exits  = {ce_:.1f}")
    print(f"mean max_loop      = {ml:.0f}")
    print(f"\nGATE (user): eWkill >= 80% (24/30) AND death <= 20%")
    print(f"  -> {'PASS' if eWkill >= 24 and deaths/n*100 <= 20 else 'FAIL'} "
          f"(eWkill={eWkill}/30, death={deaths/n*100:.0f}%)")

    # STEP 2: trajectory audit on a few seeds
    print(f"\n=== STEP 2: B1 vs Oracle trajectory audit (seeds {AUDIT_SEEDS}) ===")
    for s in AUDIT_SEEDS:
        r = run_episode(s, dump=True)
        print(f"\n--- seed {s}: kills={r['kills']} dead={r['dead']} "
              f"first_div shown below ---")
        print(f"{'step':>4s} {'phase':>9s} {'B1':>14s} {'Oracle':>14s} {'DIV':>6s}")
        first_div_shown = False
        for (st, ph, b, o, dv) in r["trace"]:
            mark = dv if (dv and not first_div_shown) else (""
                         if not dv else "")
            if dv and not first_div_shown:
                first_div_shown = True
                mark = dv
            print(f"{st:>4d} {ph:>9s} {b:>14s} {o:>14s} {mark:>6s}")
            if first_div_shown and st > (r["trace"][0][0] + 40):
                break
    print("\nNOTE: BC-only audit. No DAgger, no PPO. Stop here; wait for OK.")


if __name__ == "__main__":
    main()
