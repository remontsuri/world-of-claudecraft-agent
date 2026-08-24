"""CLEAN ABLATION TEST — isolate combat-latch vs navigation representation.

NO PPO, NO Sim/reward/obs/action changes. Plain BC (supervised) on the SAME
Oracle dataset, SAME seeds, SAME MLP/optimizer/loss/budget as bc_nav_model.py
and bc_nav_eval.py. Only the DERIVED FEATURE SET varies.

Variants (derived features appended to the 567 raw obs):
  A  : []                                  (raw only — honest baseline)
  B1 : [in_combat_range]                    (combat-mode latch ONLY)
  B2 : [turn_dir, turn_strength, forward_ok](navigation representation ONLY)
  B3 : [in_combat_range, turn_dir, turn_strength, forward_ok]  (both)

NOTE: this deliberately drops mob_sin/mob_cos/target_has/target_dist that the
OLD B carried, so the two hypotheses are cleanly separated:
  - if B1 >> A  -> missing explicit combat-mode state is the key problem
  - if B2 >> A  -> navigation representation is the key problem
  - if only B3 >> both -> BOTH problems exist independently

Gate = episodes_with_kill / total_episodes >= 8/10  (NOT total_kills).

Run:
  therock-test/Scripts/python.exe bc_nav_ablation.py
"""
from __future__ import annotations

import argparse
import json
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
from torch.utils.data import TensorDataset, DataLoader

import audit_common as ac
import curriculum_env as ce
import nav_features as nf

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "nav_data" / "oracle_nav_traces.jsonl"
OUT_DIR = ROOT / "nav_data"
ABILITY_SLOTS = (ac.TGT - 16) // 2  # 48

# ---- ablation feature sets ------------------------------------------------
VARIANTS = {
    "A":  [],
    "B1": ["in_combat_range"],
    "B2": ["turn_dir", "turn_strength", "forward_ok"],
    "B3": ["in_combat_range", "turn_dir", "turn_strength", "forward_ok"],
}

EVAL_SEEDS = [42, 43, 44, 45, 46, 47, 48, 49, 50, 51]


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


# ---------------------------------------------------------------------------
# TRAIN
# ---------------------------------------------------------------------------
def load_rows(feat_keys):
    rows = []
    with open(DATA, "r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    base_obs = np.asarray([r["obs"] for r in rows], dtype=np.float32)
    actions = np.asarray([r["action"] for r in rows], dtype=np.int64)
    phases = np.asarray([r["phase"] for r in rows])
    if feat_keys:
        feats = np.asarray(
            [[float(r[k]) for k in feat_keys] for r in rows], dtype=np.float32)
        X = np.concatenate([base_obs, feats], axis=1)
    else:
        X = base_obs
    return X, actions, phases


def train_variant(variant, feat_keys, epochs=40, batch=2048, lr=1e-3):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    X, actions, phases = load_rows(feat_keys)
    obs_dim = X.shape[1]
    n_act = int(actions.max()) + 1

    rng = np.random.default_rng(0)
    idx = []
    for ph in np.unique(phases):
        p = np.where(phases == ph)[0]
        if len(p) > 6000:
            p = rng.choice(p, 6000, replace=False)
        idx.append(p)
    idx = np.concatenate(idx)
    rng.shuffle(idx)
    X, actions = X[idx], actions[idx]

    counts = np.bincount(actions, minlength=n_act).astype(np.float64)
    counts[counts == 0] = 1.0
    w = (counts.sum() / (n_act * counts)) ** 0.5
    crit = nn.CrossEntropyLoss(weight=torch.from_numpy(w).float().to(device))

    model = BCPolicy(obs_dim, n_act).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    ds = TensorDataset(torch.from_numpy(X), torch.from_numpy(actions))
    dl = DataLoader(ds, batch_size=batch, shuffle=True, num_workers=0)

    for ep in range(epochs):
        model.train()
        tot, n = 0.0, 0
        for xb, yb in dl:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
            tot += loss.item() * xb.size(0)
            n += xb.size(0)
        if (ep + 1) % 10 == 0 or ep == epochs - 1:
            print(f"  [{variant}] epoch {ep+1:3d}/{epochs} loss={tot/n:.4f}",
                  flush=True)

    out = OUT_DIR / f"bc_nav_{variant}.pt"
    torch.save({"state_dict": model.state_dict(), "obs_dim": obs_dim,
                "n_act": n_act, "variant": variant, "feat_keys": feat_keys}, out)
    print(f"SAVED {out}  (feat_keys={feat_keys})")


# ---------------------------------------------------------------------------
# EVAL
# ---------------------------------------------------------------------------
def heading_err_deg(act, mob_sin, aid):
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
        return None
    return abs(agent_heading - mob_bearing)


def first_divergence(state, act, mob_sin, aid):
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


def eval_variant(variant, feat_keys, seeds=EVAL_SEEDS):
    ckpt = torch.load(OUT_DIR / f"bc_nav_{variant}.pt",
                      map_location="cpu", weights_only=True)
    model = BCPolicy(ckpt["obs_dim"], ckpt["n_act"])
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    aid = None
    per_seed = []
    # global accumulators
    atk_close_total = 0
    close_total = 0

    print(f"\n===== EVAL {variant} (feat_keys={feat_keys}) =====")
    print(f"{'seed':>4s} {'eKill':>5s} {'eWkill':>6s} {'dmg':>5s} {'dead':>4s} "
          f"{'atk<5%':>6s} {'minD':>5s} {'fwd%':>6s} {'tn%':>6s} {'th%':>6s} | 1st_div")
    for seed in seeds:
        env = ce.CurriculumEnv(stage=3, player_class="warrior",
                               max_steps=400, frame_skip=5)
        obs, info = env.reset(seed=seed)
        if aid is None:
            aid = ac.make_aid(env.action_names)
        actions = []
        fwd = tn = th = atk = 0
        min_d = None
        head_err_sum = 0.0
        head_err_n = 0
        atk_close = 0
        close_n = 0
        tgt_switches = 0
        prev_th = 0
        ep_deaths = 0
        dead = 0
        final_kills = 0
        div = None
        div_step = None
        tracker = nf.CombatRangeTracker()
        for i in range(1, 401):
            target0, mob0 = nf.decode_nav_obs(obs, ABILITY_SLOTS)
            icr_now = tracker.update(bool(target0["has"]), target0["dist"])
            with torch.no_grad():
                if feat_keys:
                    nfobj = nf.make_nav_features(
                        mob_dist=(mob0["dist"] if mob0 else nf.MOB_SAT * nf.DIST_SCALE),
                        mob_sin=(mob0["sin"] if mob0 else 0.0),
                        mob_cos=(mob0["cos"] if mob0 else 0.0),
                        target_has=bool(target0["has"]),
                        target_dist=target0["dist"],
                        target_sin=target0["sin"], target_cos=target0["cos"],
                        in_combat_range=icr_now)
                    feats = np.asarray(
                        [[float(icr_now if k == "in_combat_range" else getattr(nfobj, k))
                          for k in feat_keys]], dtype=np.float32)
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
            ms = mob["sin"] if mob else None
            if (mob is not None) or target["has"]:
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
            cur_th = 1 if target["has"] else 0
            if prev_th != cur_th:
                tgt_switches += 1
                prev_th = cur_th
            dmg = info.get("damageDealt", 0) or 0
            kills = info.get("kills", 0) or 0
            deaths = info.get("deaths", 0) or 0
            ep_deaths = max(ep_deaths, deaths)
            if deaths > 0 or p["dead"]:
                dead = 1
            final_kills = max(final_kills, kills)
            if div is None:
                d = first_divergence(
                    nf.make_nav_features(
                        mob_dist=(mob["dist"] if mob else nf.MOB_SAT * nf.DIST_SCALE),
                        mob_sin=(mob["sin"] if mob else 0.0),
                        mob_cos=(mob["cos"] if mob else 0.0),
                        target_has=bool(target["has"]),
                        target_dist=target["dist"], target_sin=target["sin"],
                        target_cos=target["cos"]).phase,
                    act, ms if mob else 0.0, aid)
                if d:
                    div = d
                    div_step = i
            obs = nxt
            if term or trunc:
                break
        env.close()
        total = len(actions)
        c = lambda x: (x / total * 100 if total else 0.0)
        atk_close_pct = (atk_close / close_n * 100) if close_n else float("nan")
        print(f"{seed:>4d} {final_kills:>5d} {int(final_kills>0):>6d} "
              f"{dmg:>5.0f} {dead:>4d} {atk_close_pct:>6.1f} "
              f"{(min_d if min_d is not None else -1):>5.1f} {c(fwd):>6.1f} "
              f"{c(tn):>6.1f} {c(th):>6.1f} | {str(div)}@{div_step}")
        per_seed.append({
            "total_kills": int(final_kills),
            "episodes_with_kill": int(final_kills > 0),
            "deaths": int(ep_deaths),
            "dead": dead,
            "damage": float(dmg),
            "atk_close_pct": atk_close_pct,
            "min_d": min_d if min_d is not None else -1.0,
            "fwd_pct": c(fwd),
            "tn_pct": c(tn),
            "th_pct": c(th),
            "div": div,
            "tgt_switches": tgt_switches,
        })
        atk_close_total += atk_close
        close_total += close_n

    n = len(per_seed)
    total_kills = sum(s["total_kills"] for s in per_seed)
    episodes_with_kill = sum(s["episodes_with_kill"] for s in per_seed)
    deaths_total = sum(s["deaths"] for s in per_seed)
    dead_eps = sum(s["dead"] for s in per_seed)
    damage = np.mean([s["damage"] for s in per_seed])
    atk_pct = np.nanmean([s["atk_close_pct"] for s in per_seed])
    min_d = np.mean([s["min_d"] for s in per_seed])
    fwd = np.mean([s["fwd_pct"] for s in per_seed])
    tn = np.mean([s["tn_pct"] for s in per_seed])
    th = np.mean([s["th_pct"] for s in per_seed])
    divs = [s["div"] for s in per_seed if s["div"]]
    fd = max(set(divs), key=divs.count) if divs else "none"
    gate = episodes_with_kill >= 8

    print(f"\n--- {variant} SUMMARY ---")
    print(f"total_kills            = {total_kills}")
    print(f"episodes_with_kill     = {episodes_with_kill}/{n}")
    print(f"deaths (total events)  = {deaths_total}")
    print(f"death_rate             = {dead_eps/n*100:.0f}%  ({dead_eps}/{n} episodes died)")
    print(f"damage                 = {damage:.0f}")
    print(f"atk%<5yd               = {atk_pct:.1f}")
    print(f"minD                   = {min_d:.1f}")
    print(f"forward%               = {fwd:.1f}")
    print(f"target_nearest%        = {tn:.1f}")
    print(f"target_has%            = {th:.1f}")
    print(f"first_divergence       = {fd}")
    print(f"GATE (episodes_with_kill>=8/10): {gate}")

    counts_path = OUT_DIR / f"bc_nav_{variant}_counts.json"
    with open(counts_path, "w") as f:
        json.dump({"atk_close": int(atk_close_total),
                   "close": int(close_total)}, f)

    return {
        "variant": variant, "feat_keys": feat_keys,
        "total_kills": total_kills, "episodes_with_kill": episodes_with_kill,
        "n": n, "deaths_total": deaths_total, "dead_eps": dead_eps,
        "death_rate": dead_eps / n * 100, "damage": damage,
        "atk_pct": atk_pct, "min_d": min_d, "fwd": fwd, "tn": tn, "th": th,
        "fd": fd, "gate": gate,
        "counts": {"atk_close": int(atk_close_total), "close": int(close_total)},
    }


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true", help="train all variants first")
    ap.add_argument("--only", choices=list(VARIANTS), default=None,
                    help="run only one variant (train+eval)")
    ap.add_argument("--skip-train", action="store_true",
                    help="eval only (assume .pt already exist)")
    args = ap.parse_args()

    variants = [args.only] if args.only else list(VARIANTS)

    if not args.skip_train:
        for v in variants:
            print(f"\n##### TRAIN {v} #####")
            train_variant(v, VARIANTS[v])

    summaries = []
    for v in variants:
        summaries.append(eval_variant(v, VARIANTS[v]))

    # combined table
    print("\n\n========== ABLATION COMBINED TABLE ==========")
    hdr = (f"{'var':>4s} | {'totKill':>7s} {'eWkill':>6s} {'death%':>6s} "
           f"{'dmg':>5s} {'atk<5%':>6s} {'minD':>5s} {'fwd%':>6s} {'tn%':>6s} "
           f"{'th%':>6s} | {'gate':>5s}")
    print(hdr)
    print("-" * len(hdr))
    for s in summaries:
        print(f"{s['variant']:>4s} | {s['total_kills']:>7d} "
              f"{s['episodes_with_kill']:>3d}/{s['n']:<2d} "
              f"{s['death_rate']:>5.0f}% {s['damage']:>5.0f} "
              f"{s['atk_pct']:>6.1f} {s['min_d']:>5.1f} {s['fwd']:>6.1f} "
              f"{s['tn']:>6.1f} {s['th']:>6.1f} | {str(s['gate']):>5s}")

    print("\nINTERPRETATION:")
    print("  B1 >> A  -> key problem = missing explicit combat-mode state")
    print("  B2 >> A  -> key problem = navigation representation")
    print("  only B3 >> both -> BOTH problems exist independently")
    print("\nNOTE: BC-only ablation. PPO was NOT tested. Stop here; wait for OK.")
    # save combined summary
    with open(OUT_DIR / "bc_nav_ablation_summary.json", "w") as f:
        json.dump(summaries, f, indent=2)
    print("Saved bc_nav_ablation_summary.json")


if __name__ == "__main__":
    main()
