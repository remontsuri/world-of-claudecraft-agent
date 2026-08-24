"""BC navigation models — Model A (raw obs) vs Model B (obs + derived features).

NO PPO, NO RNN, NO Sim/reward/obs changes. Plain MLP classifiers.
Trained on oracle_nav_traces.jsonl (collected by oracle_nav_dataset.py).

Model A: 567 obs -> 512 -> 256 -> 128 -> 61 actions   (honest baseline)
Model B: 567 obs + derived nav features -> same MLP    (diagnostic: does giving
         turn_dir/forward_ok explicitly fix navigation? If B >> A, the fault is
         the sin/cos representation; if B == A, sin/cos is not the main issue.)

Run:
  therock-test/Scripts/python.exe bc_nav_model.py --model A
  therock-test/Scripts/python.exe bc_nav_model.py --model B
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

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "nav_data" / "oracle_nav_traces.jsonl"
OUT_A = ROOT / "nav_data" / "bc_nav_A.pt"
OUT_B = ROOT / "nav_data" / "bc_nav_B.pt"

# derived feature keys appended to obs for Model B
FEAT_KEYS = ["mob_sin", "mob_cos", "turn_dir", "turn_strength",
             "forward_ok", "target_has", "target_dist", "in_combat_range"]


class BCPolicy(nn.Module):
    def __init__(self, obs_dim: int, n_actions: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, 512), nn.ReLU(),
            nn.Linear(512, 256), nn.ReLU(),
            nn.Linear(256, 128), nn.ReLU(),
            nn.Linear(128, n_actions),
        )

    def forward(self, x):
        return self.net(x)


def load_rows(model):
    rows = []
    with open(DATA, "r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    base_obs = np.asarray([r["obs"] for r in rows], dtype=np.float32)
    actions = np.asarray([r["action"] for r in rows], dtype=np.int64)
    phases = np.asarray([r["phase"] for r in rows])
    if model == "B":
        feats = np.asarray(
            [[float(r[k]) for k in FEAT_KEYS] for r in rows], dtype=np.float32)
        X = np.concatenate([base_obs, feats], axis=1)
    else:
        X = base_obs
    return X, actions, phases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["A", "B"], required=True)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=2048)
    ap.add_argument("--lr", type=float, default=1e-3)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    X, actions, phases = load_rows(args.model)
    obs_dim = X.shape[1]
    n_act = int(actions.max()) + 1

    # balance: cap COMBAT phase (90% of data) so BC learns the sequence
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
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    ds = TensorDataset(torch.from_numpy(X), torch.from_numpy(actions))
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, num_workers=0)

    for ep in range(args.epochs):
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
        if (ep + 1) % 5 == 0 or ep == args.epochs - 1:
            print(f"  [{args.model}] epoch {ep+1:3d}/{args.epochs} "
                  f"loss={tot/n:.4f}", flush=True)

    out = OUT_B if args.model == "B" else OUT_A
    torch.save({"state_dict": model.state_dict(), "obs_dim": obs_dim,
                "n_act": n_act, "model": args.model}, out)
    print(f"SAVED {out}")


if __name__ == "__main__":
    main()
