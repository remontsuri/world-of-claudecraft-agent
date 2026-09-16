"""fly_ppo_agent.py — Full PPO-ready FlyBrain agent for WoC.

Architecture (from fly-craftax + Fly Dino + FLYT3 patterns):
  obs → sensory_encoder(obs) → LIF steps on FROZEN MaleCNS → DN activity → actor/critic heads

Key invariant: connectome weights NEVER get gradients. Only sensory_encoder, actor, critic train.
This is the frozen-feature-extractor pattern proven by fly-craftax / FLYT3 / Fly Dino.
"""
import sys
from pathlib import Path
# Add repo root to path so `from src.fly_brain...` works regardless of CWD
_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import torch
import torch.nn as nn
import numpy as np

from src.fly_brain.engine import (
    BrainEngine, SparseLIFModel, get_device, load_male_cns_weights
)


def _load_body2idx(data_dir='D:/world-of-claudecraft/data/male_cns'):
    """Load bodyId -> engine index mapping from MaleCNS annotations."""
    try:
        import pyarrow.feather as ft
        ann = ft.read_table(f'{data_dir}/body-annotations.feather').to_pandas()
        return {int(b): i for i, b in enumerate(ann['bodyId'])}
    except Exception as e:
        print(f"[agent] WARN: body2idx load failed: {e}")
        return {}


class FlyBrainPPOActorCritic(nn.Module):
    """PPO Actor-Critic with frozen MaleCNS brain as feature extractor.

    obs_dim: dimensionality of WoC observation vector (e.g., 8)
    action_dim: number of WoC actions (7: forward, turn left/right, attack, target, loot, rest)
    sensory_dim: how many neurons we inject current into (default 512 visual projection)
    lif_steps: number of LIF simulation steps per act() call (temporal integration)
    """

    def __init__(
        self,
        obs_dim: int,
        action_dim: int,
        sensory_dim: int = 512,
        lif_steps: int = 5,
        pretrained_brain=None,
        body2idx=None,
    ):
        super().__init__()
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.sensory_dim = sensory_dim
        self.lif_steps = lif_steps

        # === Frozen brain (MaleCNS 211K neurons, 26M synapses) ===
        if pretrained_brain is not None:
            self.brain = pretrained_brain
        else:
            device = get_device()
            W_sparse, n_neurons = load_male_cns_weights()
            # Load body2idx mapping from annotations
            body2idx = _load_body2idx()
            self.brain = BrainEngine(device=device)
            self.brain.initialize(W_sparse=W_sparse, n_neurons=n_neurons, body2idx=body2idx)

        # Freeze ALL brain parameters — connectome is fixed
        for p in self.brain.model.parameters():
            p.requires_grad = False
        self.brain.model.eval()

        # DN readout indices: DNg13 L/R, DNp01 (Giant Fiber) L/R
        # These are bodyIds; engine resolves via body2idx mapping
        self.dn_body_ids = [11074, 512006, 10010, 10001]
        dn_indices = self.brain.get_dn_indices(self.dn_body_ids)
        self.register_buffer('dn_idx', torch.tensor(dn_indices, dtype=torch.long))
        num_dn = len(dn_indices)

        # === Trainable sensory encoder ===
        # Game obs → input currents for sensory neurons
        # Output bounded to [0, 10000] Hz for Poisson spike generator
        # (prob_scale = dt/1000 = 0.0001; rates must be ≤ 1/prob_scale)
        self.sensory_encoder = nn.Sequential(
            nn.Linear(obs_dim, 64),
            nn.ReLU(),
            nn.Linear(64, sensory_dim),
            nn.Hardtanh(min_val=0.0, max_val=5000.0),  # bound for Poisson
        )

        # === Trainable PPO heads (actor + critic on DN features) ===
        self.actor = nn.Linear(num_dn, action_dim)
        self.critic = nn.Linear(num_dn, 1)

        # Small noise on DN features for exploration during training
        self.feature_dropout = nn.Dropout(0.1)

    def _forward_brain(self, obs):
        """obs: (batch, obs_dim) -> DN activity (batch, num_dn)."""
        # Encode game obs into input currents
        currents = self.sensory_encoder(obs)  # (batch, sensory_dim)

        # Run LIF for lif_steps timesteps
        # brain.step expects (batch, n_neurons) current injection
        batch_size = obs.shape[0]
        full_current = torch.zeros(batch_size, self.brain.n_neurons, device=obs.device)
        # Inject into first sensory_dim neurons (visual projection group)
        full_current[:, :self.sensory_dim] = currents

        # Simulate
        for _ in range(self.lif_steps):
            self.brain.step(full_current)

        # Read DN activity
        rates = self.brain.get_dn_rates(self.dn_idx)  # (batch, num_dn)
        return rates

    def forward(self, obs):
        """obs: (batch, obs_dim) -> (action_logits (batch, action_dim), value (batch, 1))"""
        with torch.no_grad():
            dn_features = self._forward_brain(obs)
        dn_features = self.feature_dropout(dn_features)
        return self.actor(dn_features), self.critic(dn_features)

    def act(self, obs_np):
        """Single obs -> action, log_prob, value. For rollout collection."""
        self.eval()
        with torch.no_grad():
            obs_t = torch.tensor(obs_np, dtype=torch.float32).unsqueeze(0)
            logits, value = self.forward(obs_t)
            probs = torch.softmax(logits, dim=-1)
            dist = torch.distributions.Categorical(probs)
            action = dist.sample()
            log_prob = dist.log_prob(action)
            return action.item(), log_prob.item(), value.item()

    def evaluate_actions(self, obs_batch, actions):
        """For PPO update: given batch of obs+actions, return log_probs, values, entropy."""
        logits, values = self.forward(obs_batch)
        probs = torch.softmax(logits, dim=-1)
        dist = torch.distributions.Categorical(probs)
        log_probs = dist.log_prob(actions)
        entropy = dist.entropy()
        return log_probs, values.squeeze(-1), entropy


class NegativeControlMLP(nn.Module):
    """Baseline: same parameter count as FlyBrainPPOActorCritic but WITHOUT connectome.

    If fly brain doesn't beat this on reward, the connectome isn't contributing.
    FLYT3 reported MLP beating connectome 85.7% vs 60.8% — this is our negative control.
    """

    def __init__(self, obs_dim, action_dim, hidden=128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.ReLU(),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )
        self.actor = nn.Linear(hidden, action_dim)
        self.critic = nn.Linear(hidden, 1)

    def forward(self, obs):
        h = self.net(obs)
        return self.actor(h), self.critic(h)

    def act(self, obs_np):
        self.eval()
        with torch.no_grad():
            obs_t = torch.tensor(obs_np, dtype=torch.float32).unsqueeze(0)
            logits, value = self.forward(obs_t)
            probs = torch.softmax(logits, dim=-1)
            dist = torch.distributions.Categorical(probs)
            action = dist.sample()
            log_prob = dist.log_prob(action)
            return action.item(), log_prob.item(), value.item()

    def evaluate_actions(self, obs_batch, actions):
        logits, values = self.forward(obs_batch)
        probs = torch.softmax(logits, dim=-1)
        dist = torch.distributions.Categorical(probs)
        log_probs = dist.log_prob(actions)
        entropy = dist.entropy()
        return log_probs, values.squeeze(-1), entropy


if __name__ == "__main__":
    # Smoke test
    obs_dim, action_dim = 8, 7
    fly = FlyBrainPPOActorCritic(obs_dim=obs_dim, action_dim=action_dim, sensory_dim=64, lif_steps=2)
    mlp = NegativeControlMLP(obs_dim=obs_dim, action_dim=action_dim)

    obs = np.random.randn(obs_dim).astype(np.float32)

    fly_action, fly_lp, fly_v = fly.act(obs)
    print(f"[fly]   action={fly_action}, log_prob={fly_lp:.3f}, value={fly_v:.3f}")

    mlp_action, mlp_lp, mlp_v = mlp.act(obs)
    print(f"[mlp]   action={mlp_action}, log_prob={mlp_lp:.3f}, value={mlp_v:.3f}")

    fly_params = sum(p.numel() for p in fly.parameters() if p.requires_grad)
    mlp_params = sum(p.numel() for p in mlp.parameters() if p.requires_grad)
    print(f"[params] fly trainable={fly_params}, mlp trainable={mlp_params}")
    print("[fly_ppo_agent] OK")
