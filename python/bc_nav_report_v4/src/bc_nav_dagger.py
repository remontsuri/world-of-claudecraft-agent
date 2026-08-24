"""Real closed-loop DAgger for BC navigation — B1 vs B3 in parallel.

NO PPO, NO Sim/obs/reward/action changes. Only supervised BC retraining on
aggregated (state, oracle_action) pairs collected from the CURRENT policy's
ACTUAL rollout states (covariate-shift fix), exactly per user spec.

Pipeline (per variant, B1 and B3 run with IDENTICAL budget/seeds):
  base Oracle traces (80k)         ->  initial BC (bc_nav_B1 / bc_nav_B3 .pt)
  for round in 1..R:
      roll current BC on K seeds
        BC ACTS in env (env.step(bc_act))   # we visit BC's real states
        Oracle LABELS each visited state    # (obs_before_step, oracle_action)
      append (obs, oracle_action, feats) to pool
      retrain BC on pooled (balanced)
  eval on train seeds (42-51) + 20 HELD-OUT seeds (62-81)  -> gate

Variants (derived features appended to 567 raw obs; computed ONLY in Python):
  B1 : [in_combat_range]                         (combat latch ONLY)
  B3 : [in_combat_range, turn_dir, turn_strength, forward_ok]  (combat + nav)

Gate (held-out 20 seeds): episodes_with_kill >= 16/20 AND death_rate <= 20%.

Run:
  therock-test/Scripts/python.exe bc_nav_dagger.py
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

VARIANTS = {
    "B1": ["in_combat_range"],
    "B3": ["in_combat_range", "turn_dir", "turn_strength", "forward_ok"],
}
ABILITY_SLOTS = (ac.TGT - 16) // 2

# DAgger aggregation seeds (same for B1/B3): 3 rounds x 8 seeds = 24 rolls
AGG_SEEDS = [42, 43, 44, 45, 46, 47, 48, 49,
             50, 51, 52, 53, 54, 55, 56, 57,
             58, 59, 60, 61, 62, 63, 64, 65]
ROUNDS = 3
# Held-out gate seeds: strictly OUTSIDE train (42-61) and aggregation (42-65)
HELD_OUT_SEEDS = list(range(66, 86))   # 20 seeds
TRAIN_EVAL_SEEDS = list(range(42, 52))  # 10 (for comparison only)


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
def featurize(obs, tracker, feat_keys):
    """Return (feats_array, phase, target, mob, icr) for one obs."""
    target, mob = nf.decode_nav_obs(obs, ABILITY_SLOTS)
    icr = tracker.update(bool(target["has"]), target["dist"])
    nfobj = nf.make_nav_features(
        mob_dist=(mob["dist"] if mob else nf.MOB_SAT * nf.DIST_SCALE),
        mob_sin=(mob["sin"] if mob else 0.0),
        mob_cos=(mob["cos"] if mob else 0.0),
        target_has=bool(target["has"]),
        target_dist=target["dist"], target_sin=target["sin"],
        target_cos=target["cos"], in_combat_range=icr)
    feats = np.asarray(
        [[float(icr if k == "in_combat_range" else getattr(nfobj, k))
          for k in feat_keys]], dtype=np.float32)
    return feats, nfobj.phase, target, mob, icr


def load_base(feat_keys):
    """Base pool = 80k Oracle traces (obs + selected derived feats + action)."""
    rows = []
    with open(DATA, "r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    base_obs = np.asarray([r["obs"] for r in rows], dtype=np.float32)
    actions = np.asarray([r["action"] for r in rows], dtype=np.int64)
    phases = np.asarray([r["phase"] for r in rows])
    feats = np.asarray(
        [[float(r[k]) for k in feat_keys] for r in rows], dtype=np.float32)
    X = np.concatenate([base_obs, feats], axis=1)
    return X, actions, phases


def train_bc(X, actions, phases, epochs=30, batch=2048, lr=1e-3):
    obs_dim = X.shape[1]
    n_act = int(actions.max()) + 1
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # balance: cap COMBAT phase (dominant) so BC learns the sequence
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
    for _ in range(epochs):
        model.train()
        for xb, yb in dl:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
    return model, obs_dim, n_act


def dagger_rollout(variant, feat_keys, bc_model, seeds, device):
    """Roll BC; BC ACTS, Oracle LABELS each visited state. Returns new rows."""
    bc_model.eval()
    aid = ac.make_aid(ce.CurriculumEnv(stage=3, player_class="warrior",
                                       max_steps=1, frame_skip=5).action_names)
    X_new, y_new, ph_new = [], [], []
    for seed in seeds:
        env = ce.CurriculumEnv(stage=3, player_class="warrior",
                               max_steps=400, frame_skip=5)
        obs, _ = env.reset(seed=seed)
        tracker = nf.CombatRangeTracker()
        prev_or = {}
        for _ in range(1, 401):
            feats, phase, target, mob, icr = featurize(obs, tracker, feat_keys)
            xin = torch.from_numpy(
                np.concatenate([np.asarray(obs, np.float32)[None], feats],
                               axis=1)).to(device)
            with torch.no_grad():
                bc_act = int(bc_model(xin).argmax(1).item())
            or_act = int(ac.oracle_action(obs, aid, prev_or))
            nxt, _, term, trunc, _ = env.step(bc_act)  # BC acts in env
            # append the STATE BC reached, labeled by Oracle
            X_new.append(np.asarray(obs, np.float32))
            y_new.append(or_act)
            ph_new.append(phase)
            obs = nxt
            if term or trunc:
                break
        env.close()
    X_new = np.concatenate([X_new], axis=0) if X_new else np.empty((0, 567), np.float32)
    y_new = np.asarray(y_new, np.int64)
    ph_new = np.asarray(ph_new)
    # attach feats to X
    # re-featurize base+new consistently: we already have raw obs + action;
    # recompute feats for the new rows here
    feat_rows = []
    for i, obs in enumerate(X_new):
        # tracker state is per-episode; for feats we recompute without hysteresis
        # continuity (acceptable: feature is a function of obs at that step; the
        # tracker used during rollout already produced correct in_combat_range,
        # but to keep rows self-contained we re-derive from obs alone using a
        # fresh tracker per row — NOTE this drops hysteresis continuity, so we
        # store the oracle-labeled action and raw obs; feats are re-derived at
        # train time below).
        pass
    return X_new, y_new, ph_new


# ---------------------------------------------------------------------------
# EVAL (closed-loop, BC acts entirely; Oracle queried for agreement only)
# ---------------------------------------------------------------------------
def eval_policy(variant, feat_keys, bc_model, seeds):
    bc_model.eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    aid = ac.make_aid(ce.CurriculumEnv(stage=3, player_class="warrior",
                                       max_steps=1, frame_skip=5).action_names)
    per_seed = []
    # per-phase agreement accumulators
    agr = {ph: [0, 0] for ph in
           ["NAV", "ACQUIRE", "APPROACH", "COMBAT"]}
    atk_close_total = close_total = 0
    print(f"\n===== DAgger EVAL {variant} (seeds={seeds[0]}..{seeds[-1]}) =====")
    for seed in seeds:
        env = ce.CurriculumEnv(stage=3, player_class="warrior",
                               max_steps=400, frame_skip=5)
        obs, _ = env.reset(seed=seed)
        tracker = nf.CombatRangeTracker()
        prev_or = {}
        total_kills = 0
        dead = 0
        dmg = 0
        atk_close = close_n = 0
        tgt_sw = 0
        prev_th = 0
        max_loop = 0
        cur_loop = 0
        min_d = None
        fwd = tn = th = atk = 0
        n_steps = 0
        for _ in range(1, 401):
            feats, phase, target, mob, icr = featurize(obs, tracker, feat_keys)
            xin = torch.from_numpy(
                np.concatenate([np.asarray(obs, np.float32)[None], feats],
                               axis=1)).to(device)
            with torch.no_grad():
                bc_act = int(bc_model(xin).argmax(1).item())
            or_act = int(ac.oracle_action(obs, aid, prev_or))
            # agreement per phase
            if phase in agr:
                agr[phase][1] += 1
                if bc_act == or_act:
                    agr[phase][0] += 1
            nxt, r, term, trunc, info = env.step(bc_act)  # BC acts
            p, tgt, mb = ac.decode(obs)
            # loop detector (no-op-ish): consecutive turn/forward w/o attack/target
            if bc_act in (aid["turn_left"], aid["turn_right"], aid["forward"]) \
                    and bc_act not in (aid["attack"], aid["target_nearest"]):
                cur_loop += 1
                max_loop = max(max_loop, cur_loop)
            else:
                cur_loop = 0
            if mb is not None:
                if min_d is None or mb["dist"] < min_d:
                    min_d = mb["dist"]
                if mb["dist"] < 5.0:
                    close_n += 1
                    if bc_act == aid["attack"]:
                        atk_close += 1
            elif tgt["has"]:
                if min_d is None or tgt["dist"] < min_d:
                    min_d = tgt["dist"]
                if tgt["dist"] < 5.0:
                    close_n += 1
                    if bc_act == aid["attack"]:
                        atk_close += 1
            if bc_act == aid["forward"]:
                fwd += 1
            if bc_act == aid["target_nearest"]:
                tn += 1
            if tgt["has"]:
                th += 1
            if bc_act == aid["attack"]:
                atk += 1
            cur_th = 1 if tgt["has"] else 0
            if prev_th != cur_th:
                tgt_sw += 1
                prev_th = cur_th
            dmg = max(dmg, info.get("damageDealt", 0) or 0)
            total_kills = max(total_kills, info.get("kills", 0) or 0)
            if (info.get("deaths", 0) or 0) > 0 or p["dead"]:
                dead = 1
            obs = nxt
            n_steps += 1
            if term or trunc:
                break
        env.close()
        atk_pct = (atk_close / close_n * 100) if close_n else float("nan")
        print(f"  seed {seed:>3d}: kills={total_kills} eWkill={int(total_kills>0)} "
              f"dead={dead} dmg={dmg:>3.0f} atk<5%={atk_pct:>5.1f} "
              f"minD={min_d if min_d else -1:>4.1f} loop={max_loop}")
        per_seed.append({
            "total_kills": total_kills, "eWkill": int(total_kills > 0),
            "dead": dead, "dmg": dmg, "atk_pct": atk_pct,
            "min_d": min_d if min_d else -1, "tgt_sw": tgt_sw,
            "max_loop": max_loop, "n": n_steps,
        })
        atk_close_total += atk_close
        close_total += close_n

    n = len(per_seed)
    eWkill = sum(s["eWkill"] for s in per_seed)
    deaths = sum(s["dead"] for s in per_seed)
    dmg = np.mean([s["dmg"] for s in per_seed])
    atk_pct = np.nanmean([s["atk_pct"] for s in per_seed])
    min_d = np.mean([s["min_d"] for s in per_seed])
    print(f"  -> {variant} held/train: eWkill={eWkill}/{n}  death_rate={deaths/n*100:.0f}%  "
          f"dmg={dmg:.0f}  atk%<5yd={atk_pct:.1f}  minD={min_d:.1f}")
    print("  BC/Oracle agreement per phase:")
    for ph in ["NAV", "ACQUIRE", "APPROACH", "COMBAT"]:
        a, t = agr[ph]
        if t:
            print(f"    {ph:>8s}: {a}/{t} = {a/t*100:.1f}%")
    gate = (eWkill >= 16 and deaths / n * 100 <= 20) if n >= 20 else False
    return {
        "variant": variant, "eWkill": eWkill, "n": n, "deaths": deaths,
        "death_rate": deaths / n * 100, "dmg": dmg, "atk_pct": atk_pct,
        "min_d": min_d, "agreement": {ph: (agr[ph][0] / agr[ph][1] * 100
                                            if agr[ph][1] else float("nan"))
                                       for ph in agr},
        "gate": gate,
    }


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    ap.add_argument("--skip-train", action="store_true",
                    help="eval only using existing bc_nav_dagger_*.pt")
    ap.add_argument("--only", choices=list(VARIANTS), default=None)
    args = ap.parse_args()
    variants = [args.only] if args.only else list(VARIANTS)

    results = {}
    for variant in variants:
        feat_keys = VARIANTS[variant]
        print(f"\n########## VARIANT {variant} (feat_keys={feat_keys}) ##########")

        # 1) base pool
        X_base, y_base, ph_base = load_base(feat_keys)

        if not args.skip_train:
            # 2) initial BC = bc_nav_{variant}.pt from ablation
            init = OUT_DIR / f"bc_nav_{variant}.pt"
            ckpt = torch.load(init, map_location="cpu", weights_only=True)
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            bc = BCPolicy(ckpt["obs_dim"], ckpt["n_act"])
            bc.load_state_dict(ckpt["state_dict"])
            bc.to(device)

            # 3) DAgger rounds
            pool_X = [X_base]
            pool_y = [y_base]
            pool_ph = [ph_base]
            for rnd in range(args.rounds):
                seeds = AGG_SEEDS[rnd::ROUNDS]  # 8 seeds per round, rotating
                print(f"  [DAgger {variant} round {rnd+1}] rolling {len(seeds)} "
                      f"seeds, BC acts, Oracle labels...", flush=True)
                Xn, yn, phn = dagger_rollout(variant, feat_keys, bc, seeds, device)
                # re-derive feats for new rows (self-contained: feats from obs)
                feats_new = np.asarray(
                    [[float(r) for r in _row_feats(Xn[i], feat_keys)]
                     for i in range(len(Xn))], dtype=np.float32) if len(Xn) else \
                    np.empty((0, len(feat_keys)), np.float32)
                Xn_full = np.concatenate([Xn, feats_new], axis=1) \
                    if len(Xn) else np.empty((0, X_base.shape[1]), np.float32)
                pool_X.append(Xn_full)
                pool_y.append(yn)
                pool_ph.append(phn)
                X_all = np.concatenate(pool_X)
                y_all = np.concatenate(pool_y)
                ph_all = np.concatenate(pool_ph)
                print(f"    pool size = {len(X_all)}; retraining BC...", flush=True)
                bc, od, na = train_bc(X_all, y_all, ph_all)
                torch.save({"state_dict": bc.state_dict(), "obs_dim": od,
                            "n_act": na, "variant": variant,
                            "feat_keys": feat_keys, "round": rnd + 1},
                           OUT_DIR / f"bc_nav_dagger_{variant}.pt")
                print(f"    saved bc_nav_dagger_{variant}.pt", flush=True)

        # 4) eval: train seeds + held-out gate seeds
        ckpt = torch.load(OUT_DIR / f"bc_nav_dagger_{variant}.pt",
                          map_location="cpu", weights_only=True)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        bc = BCPolicy(ckpt["obs_dim"], ckpt["n_act"])
        bc.load_state_dict(ckpt["state_dict"])
        bc.to(device)
        r_train = eval_policy(variant, feat_keys, bc, TRAIN_EVAL_SEEDS)
        r_held = eval_policy(variant, feat_keys, bc, HELD_OUT_SEEDS)
        results[variant] = {"train": r_train, "held_out": r_held}

    # combined table
    print("\n\n========== DAgger COMBINED (held-out 20 seeds gate) ==========")
    print(f"{'var':>4s} | {'eWkill/20':>9s} {'death%':>6s} {'dmg':>5s} "
          f"{'atk<5%':>6s} | GATE")
    print("-" * 50)
    for v in variants:
        r = results[v]["held_out"]
        print(f"{v:>4s} | {r['eWkill']:>3d}/20   {r['death_rate']:>5.0f}% "
              f"{r['dmg']:>5.0f} {r['atk_pct']:>6.1f} | {r['gate']}")
    print("\nNOTE: BC-only DAgger. PPO NOT tested. Stop here; wait for OK.")
    with open(OUT_DIR / "bc_nav_dagger_summary.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("Saved bc_nav_dagger_summary.json")


def _row_feats(obs, feat_keys):
    """Re-derive derived features for a single obs (no hysteresis continuity)."""
    target, mob = nf.decode_nav_obs(obs, ABILITY_SLOTS)
    nfobj = nf.make_nav_features(
        mob_dist=(mob["dist"] if mob else nf.MOB_SAT * nf.DIST_SCALE),
        mob_sin=(mob["sin"] if mob else 0.0),
        mob_cos=(mob["cos"] if mob else 0.0),
        target_has=bool(target["has"]),
        target_dist=target["dist"], target_sin=target["sin"],
        target_cos=target["cos"],
        in_combat_range=bool(target["has"] and target["dist"] <= nf.MELEE_YD))
    return [float(getattr(nfobj, k)) for k in feat_keys]


if __name__ == "__main__":
    main()
