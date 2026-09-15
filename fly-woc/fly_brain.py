"""Frozen MaleCNS circuit engine + engineered sensory drive (world-of-claudecraft).

Dynamics follow the Fly Dino v2 protocol (flyjump src/lib/connectome.ts):
signed, normalized, leaky-tanh rate units, 3 synchronous iterations per
decision, dimensionless activity (NOT firing rates or membrane voltage).

    W[j,i] = c[j,i] * s[j] / sum_k(c[k,i] * |s[k]|)   (normalize into post cell)
    h_new  = 0.3 * h + 0.7 * tanh(u + 1.4 * sum_j W[j,i] * h[j])
    output = 4 * h[outputCell]

Only the artificial readout downstream is trained; the graph, signs,
normalization and drive mapping are fixed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

DYNAMICS = {"iterations": 3, "leak": 0.7, "gain": 1.4, "outputGain": 4.0}  # Fly Dino v2 constants

# ---------------------------------------------------------------- observations
# WoWClassicEnv obs layout (src/sim/obs.ts, queried sizes: obs 607, actions 61):
#   self 0..15 | abilities 16..111 (48 x [ready, cd_frac]) | target 112..120
#   mobs 121..150 (5 x 6) | interactable 151..155 | quests 156..603 (224 x 2)
#   paladin tail 604..606
# 13 engineered features; the assignment to cell types is a fixed engineering
# encoder with no claimed biological interpretation (Fly Dino v2 wording).
FEATURE_NAMES = ["hp", "resource", "in_combat", "gcd_ready", "target_exists",
                 "target_dist", "target_hp", "target_sin", "target_cos",
                 "nearest_mob_dist", "mob_pressure", "ability_ready", "quest_progress"]


def extract_features(obs: np.ndarray) -> np.ndarray:
    o = obs
    mob_aggro = o[126:151:6].mean() if o.shape[0] > 150 else 0.0
    return np.array([
        o[0],                                        # hp ratio
        o[1],                                        # resource ratio
        o[11],                                       # in combat flag
        1.0 - o[8],                                  # gcd ready
        o[112],                                      # target exists
        min(o[115] / 1.5, 1.0),                      # target distance (0..1)
        o[113],                                      # target hp ratio
        (o[116] + 1.0) / 2.0,                        # target bearing sin
        (o[117] + 1.0) / 2.0,                        # target bearing cos
        min(o[121] / 1.5, 1.0),                      # nearest mob distance
        mob_aggro,                                   # fraction of mobs aggroed
        o[16:112:2].mean(),                          # ability readiness fraction
        o[157:604:2].mean(),                         # mean quest progress
    ], dtype=np.float32)


class FlyBrain:
    """Batched frozen circuit. Input: (B, 13) features. Output: (B, n_dn) torch tensor.

    The graph needs no autograd, so the propagation runs in scipy.sparse
    (OpenMP-parallel CSR); torch's CPU sparse CSR matmul measured ~234 ms per
    multiply on this graph vs ~2 ms for scipy. Only the returned DN slice
    re-enters torch, for the trainable readout.
    """

    def __init__(self, circuit_path: str | Path = Path(__file__).parent / "data" / "circuit.json",
                 device: str = "cpu"):
        from scipy.sparse import coo_matrix
        graph = json.loads(Path(circuit_path).read_text())
        self.graph = graph
        n = len(graph["nodes"])
        self.n = n
        self.device = device
        pre = np.array([e[0] for e in graph["edges"]], dtype=np.int32)
        post = np.array([e[1] for e in graph["edges"]], dtype=np.int32)
        contacts = np.array([e[2] for e in graph["edges"]], dtype=np.float64)
        signs = np.array([nd["sign"] for nd in graph["nodes"]], dtype=np.float64)

        # Fly Dino normalization: incoming signed weights normalized by the total
        # absolute signed contact count at each postsynaptic cell; zero -> 0.
        denom = np.zeros(n)
        np.add.at(denom, post, contacts * np.abs(signs[pre]))
        w = np.where(denom[post] > 0, contacts * signs[pre] / np.maximum(denom[post], 1e-12), 0.0)

        # W_T[post, pre] so that (W_T @ h.T) accumulates presynaptic activity
        # into each postsynaptic cell.
        self.W_T = coo_matrix((w.astype(np.float32), (post, pre)), shape=(n, n)).tocsr()
        self.W_T.sum_duplicates()

        self.input_idx = np.array([c for c, _ in graph["inputs"]], dtype=np.int64)
        self.input_ch = np.array([ch for _, ch in graph["inputs"]], dtype=np.int64)
        self.out_idx_np = np.array(graph["outputs"], dtype=np.int64)
        self.n_dn = len(graph["outputs"])
        self.h = None            # numpy (B, n)
        self._u = None

    def reset(self, batch: int):
        self.h = np.zeros((batch, self.n), np.float32)

    def step(self, feats, silenced: bool = False):
        """feats: (B, 13) torch tensor or numpy -> DN activities (B, n_dn) as torch tensor."""
        if isinstance(feats, torch.Tensor):
            feats = feats.detach().cpu().numpy()
        B = feats.shape[0]
        if self.h is None or self.h.shape[0] != B:
            self.reset(B)
        if silenced:
            self.h[:] = 0
            return torch.zeros(B, self.n_dn)
        u = np.zeros((B, self.n), np.float32)
        # Fly Dino drive encoding: u = 2 * (feature - 0.5) on driven cells only.
        u[:, self.input_idx] = 2.0 * (feats[:, self.input_ch] - 0.5)
        leak = DYNAMICS["leak"]; gain = DYNAMICS["gain"]
        for _ in range(DYNAMICS["iterations"]):
            inp = u + gain * (self.W_T @ self.h.T).T
            self.h = (1 - leak) * self.h + leak * np.tanh(inp, dtype=np.float32)
        out = self.h[:, self.out_idx_np] * DYNAMICS["outputGain"]
        return torch.from_numpy(np.ascontiguousarray(out))
