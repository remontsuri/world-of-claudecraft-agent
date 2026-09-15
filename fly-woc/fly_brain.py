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
import os
from pathlib import Path

import numpy as np
import torch

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))  # obs_layout рядом
from obs_layout import from_obs  # noqa: E402

DYNAMICS = {"iterations": 3, "leak": 0.7, "gain": 1.4, "outputGain": 4.0}  # Fly Dino v2 constants

# ---------------------------------------------------------------- observations
# WoWClassicEnv obs layout (src/sim/obs.ts): self 16 | abilities 2*ABILITY_SLOTS |
# target 9 | mobs 5x6 | interactable 5 | quests 2*QUEST_ORDER.length | paladin 3.
# Индексы блоков НЕ захардкожены: игра меняет ABILITY_SLOTS (48 -> 28 в текущей
# версии), и всё после способностей сдвигается. Блоки выводятся из длины obs
# через obs_layout.from_obs: 607 -> цель 112, мобы 121, интеракт 151, квесты 156;
# 567 -> цель 72, мобы 81, интеракт 111, квесты 116.
# 13 engineered features; the assignment to cell types is a fixed engineering
# encoder with no claimed biological interpretation (Fly Dino v2 wording).
# v2 channel names (same 13 slots, different semantics from index 8 on).
FEATURE_NAMES_V2 = ["hp", "resource", "in_combat", "gcd_ready", "target_exists",
                    "target_dist", "target_sin", "target_cos", "mob0_dist",
                    "mob0_sin", "mob0_cos", "interact_prox", "quest_signal"]
FEATURE_NAMES = ["hp", "resource", "in_combat", "gcd_ready", "target_exists",
                 "target_dist", "target_hp", "target_sin", "target_cos",
                 "nearest_mob_dist", "mob_pressure", "ability_ready", "quest_progress"]


def extract_features_v2(obs: np.ndarray) -> np.ndarray:
    """Navigation-aware encoder: same 13 channels, richer semantics.

    v1 collapsed the observation to 13 scalars that carry NO direction and NO
    position (it averaged quest progress and mob aggro). That is enough to fight
    whatever happens to be in front of you and to finish a quest by accident, but
    it cannot express "walk to that corpse" or "go to the quest giver", which is
    what every milestone past the starter quest needs.

    v2 keeps the SAME 13 channel slots, so the existing circuit.json (13 channels
    x 4 cells = 52 input cells) is reused unchanged and only the readout is
    retrained:

        0 hp                       [v1: same]
        1 resource                 [v1: same]
        2 in_combat                [v1: same]
        3 gcd_ready                [v1: same]
        4 target_exists            [v1: same, now hostile-aware]
        5 target_dist              [v1: same, d/40 clamped to the obs ceiling]
        6 target_sin               [v1: same]
        7 target_cos               [v1: same]
        8 mob0_dist                [v1: "nearest mob dist" - identical index]
        9 mob0_sin                 [v1: mob aggro fraction -> replaced by bearing]
       10 mob0_cos                 [same slot, other bearing component]
       11 interact_proximity       [v1: mean ability readiness -> replaced: how
                                    close the nearest interactable is, 1 = in
                                    range, which is exactly the signal that
                                    gates interact/loot/quest-NPC actions]
       12 quest_signal             [v1: mean quest progress -> now progress of the
                                    most advanced open quest (falls back to mean)]

    Observation indices are from the game's own encoder,
    src/sim/obs.ts encodeObs(): mobs 121..150 are 5 x [dist, sin, cos, hp, level,
    aggro], the interactable block is 151..155, quests are 156..603 as 224 pairs
    [progress, state] with state 'done' -> progress 1.
    """
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    n = o.shape[0]
    try:
        L = from_obs(o)
    except ValueError:               # truncated/foreign obs (tests): fall back to v1
        return extract_features_v1(obs)
    if n != L.obs_size or n < L.paladin_base:   # sanity: вектор короче раскладки
        return extract_features_v1(obs)

    # Distances in the obs are ALREADY d/40 clamped to 1.5 (the 60-unit obs
    # radius), so they only need rescaling into 0..1 - never another /40.
    def unit(i: int) -> float:
        return float(np.clip(o[i] / 1.5, 0.0, 1.0))

    # Interactable block = [exists, d/40, sin, cos, type]
    ib = L.interact_base
    interact_exists = float(o[ib])
    interact_prox = interact_exists * (1.0 - unit(ib + 1))

    # Quest block = N x [state, progress], states:
    # 0 not taken, 0.33 active, 0.66 ready to turn in, 1 done.
    quests = o[L.quest_slice()].reshape(-1, 2)
    if quests.size:
        state, progress = quests[:, 0], quests[:, 1]
        ready = bool(((state > 0.5) & (state < 1.0)).any())   # 0.66: hand it in
        active = state == 0.33
        # Prefer "something is ready to turn in" (that is the productive action),
        # else the most advanced active quest.
        quest_signal = 1.0 if ready else (float(progress[active].max()) if active.any() else 0.0)
    else:
        quest_signal = 0.0

    return np.array([
        o[0],                                        # hp ratio
        o[1],                                        # resource ratio
        o[11],                                       # in combat flag
        1.0 - o[8],                                  # gcd ready
        o[L.target_base],                            # target exists
        unit(L.target_base + 3),                     # target distance
        0.5 * (float(o[L.target_base + 4]) + 1.0),   # target bearing sin -> 0..1
        0.5 * (float(o[L.target_base + 5]) + 1.0),   # target bearing cos -> 0..1
        unit(L.mobs_base),                           # nearest hostile mob distance
        0.5 * (float(o[L.mobs_base + 1]) + 1.0),     # nearest mob bearing sin
        0.5 * (float(o[L.mobs_base + 2]) + 1.0),     # nearest mob bearing cos
        interact_prox,                               # interactable/loot/quest-NPC proximity
        quest_signal,                                # ready-to-turn-in, else max progress
    ], dtype=np.float32)


def extract_features_v1(obs: np.ndarray) -> np.ndarray:
    """Original 13-channel encoder (kept for the committed v1 checkpoints)."""
    o = np.asarray(obs, dtype=np.float32).reshape(-1)
    L = from_obs(o)
    mob_aggro = o[L.mobs_base + 5: L.interact_base: 6].mean()   # per-mob aggro flag
    return np.array([
        o[0],                                        # hp ratio
        o[1],                                        # resource ratio
        o[11],                                       # in combat flag
        1.0 - o[8],                                  # gcd ready
        o[L.target_base],                            # target exists
        min(o[L.target_base + 3] / 1.5, 1.0),        # target distance (0..1)
        o[L.target_base + 1],                        # target hp ratio
        (o[L.target_base + 4] + 1.0) / 2.0,          # target bearing sin
        (o[L.target_base + 5] + 1.0) / 2.0,          # target bearing cos
        min(o[L.mobs_base] / 1.5, 1.0),              # nearest mob distance
        mob_aggro,                                   # fraction of mobs aggroed
        o[L.ability_base: L.target_base: 2].mean(),  # ability readiness fraction
        o[L.quest_base + 1: L.quest_end: 2].mean(),  # mean quest progress
    ], dtype=np.float32)


# Feature set selector. v1 = committed checkpoints (params_fly_v2.pt); v2 =
# navigation-aware, same 13 slots, needs a retrained readout. Set FLY_FEATURES=v2.
FEATURE_VERSION = os.environ.get("FLY_FEATURES", "v1").strip().lower()


def extract_features(obs: np.ndarray) -> np.ndarray:
    """Dispatch on FLY_FEATURES so one env var switches encoder+checkpoint together."""
    return extract_features_v2(obs) if FEATURE_VERSION == "v2" else extract_features_v1(obs)


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
