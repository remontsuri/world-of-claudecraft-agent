"""Trainable readouts. The connectome is never trained; only these nets are.

FlyBrainReadout: DN activities -> actor/critic MLPs (the experimental agent).
MLPControl:      raw game observations -> actor/critic (the negative control,
                 FLYT3 lesson: without it we cannot attribute anything to the
                 circuit; their pixel-MLP beat the circuit decoder 85.7 vs 60.8).
"""
from __future__ import annotations

import torch
import torch.nn as nn


class FlyBrainReadout(nn.Module):
    def __init__(self, n_dn: int, n_actions: int, hidden: int = 64):
        super().__init__()
        self.actor = nn.Sequential(nn.Linear(n_dn, hidden), nn.Tanh(), nn.Linear(hidden, n_actions))
        self.critic = nn.Sequential(nn.Linear(n_dn, hidden), nn.Tanh(), nn.Linear(hidden, 1))

    def forward(self, feats: torch.Tensor):
        return self.actor(feats), self.critic(feats).squeeze(-1)


class MLPControl(nn.Module):
    def __init__(self, obs_dim: int, n_actions: int, hidden: int = 128):
        super().__init__()
        self.actor = nn.Sequential(nn.Linear(obs_dim, hidden), nn.Tanh(), nn.Linear(hidden, n_actions))
        self.critic = nn.Sequential(nn.Linear(obs_dim, hidden), nn.Tanh(), nn.Linear(hidden, 1))

    def forward(self, feats: torch.Tensor):
        return self.actor(feats), self.critic(feats).squeeze(-1)
