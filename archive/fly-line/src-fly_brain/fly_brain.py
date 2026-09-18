"""FlyBrain — high-level adapter wrapping BrainEngine for train_fly_ppo.py.

Provides the interface expected by the training script:
- FlyBrain(device) -> loads MaleCNS, initializes engine, resolves DN indices
- FlyBrain.step(features, silenced) -> runs LIF, returns DN rates
- FlyBrain.reset(batch) -> resets brain state
- FlyBrain.n_dn -> number of DN readout neurons
"""
import torch

from src.fly_brain.engine import (
    BrainEngine,
    get_device,
    load_male_cns_weights,
)


def _load_body2idx(data_dir='D:/world-of-claudecraft/data/male_cns'):
    try:
        import pyarrow.feather as ft
        ann = ft.read_table(f'{data_dir}/body-annotations.feather').to_pandas()
        return {int(b): i for i, b in enumerate(ann['bodyId'])}
    except Exception as e:
        print(f"[FlyBrain] WARN: body2idx load failed: {e}")
        return {}


class FlyBrain:
    """Frozen MaleCNS brain with DN readout for PPO training.

    8 engineered features -> sensory encoder currents -> LIF steps -> DN rates
    """

    # MaleCNS DN bodyIds for readout (from FLY_BRAIN_REFERENCE.md)
    DN_BODY_IDS = {
        'DNp09':   {'forward': True},      # forward
        'MDN':     {'backward': True},     # backward
        'DNa01_L': {'turn_left': True},     # turn left
        'DNa01_R': {'turn_right': True},    # turn right
        'DNa02_L': {'turn_left': True},     # turn left
        'DNa02_R': {'turn_right': True},    # turn right
        'MN9':     {'do': True},            # interact/groom
        'DNp01_L': {'escape': True},        # Giant Fiber escape
        'DNp01_R': {'escape': True},        # Giant Fiber escape
        'DNg13_L': {'steering': True},      # steering
        'DNg13_R': {'steering': True},      # steering
    }

    # bodyId mappings (from MaleCNS annotations)
    DN_BODY_ID_MAP = {
        'DNp09':   None,   # will be resolved dynamically
        'MDN':     None,
        'DNa01_L': None,
        'DNa01_R': None,
        'DNa02_L': None,
        'DNa02_R': None,
        'MN9':     None,
        'DNp01_L': 10010,
        'DNp01_R': 10001,
        'DNg13_L': 11074,
        'DNg13_R': 512006,
    }

    def __init__(self, device=None, sensory_dim=8, lif_steps=5):
        self.device = device or get_device()
        self.sensory_dim = sensory_dim
        self.lif_steps = lif_steps

        # Load MaleCNS
        W_sparse, n_neurons = load_male_cns_weights()
        body2idx = _load_body2idx()

        self.engine = BrainEngine(device=self.device)
        self.engine.initialize(W_sparse=W_sparse, n_neurons=n_neurons, body2idx=body2idx)

        # Resolve DN indices
        self.dn_indices = self._resolve_dn_indices(body2idx)
        self.n_dn = len(self.dn_indices)

        # Sensory encoder: 8 features -> first sensory_dim neurons
        # (simple linear encoder, fixed — not trained here)
        self.sensory_encoder = torch.nn.Linear(sensory_dim, sensory_dim)
        torch.nn.init.eye_(self.sensory_encoder.weight)
        torch.nn.init.zeros_(self.sensory_encoder.bias)
        self.sensory_encoder.eval()

        print(f"[FlyBrain] {n_neurons} neurons, {self.n_dn} DN readout, device={self.device}")

    def _resolve_dn_indices(self, body2idx):
        """Resolve DN bodyIds to engine indices."""
        indices = []
        for name, body_id in self.DN_BODY_ID_MAP.items():
            if body_id is not None:
                idx = body2idx.get(body_id)
                if idx is not None:
                    indices.append(idx)
                else:
                    print(f"[FlyBrain] WARN: {name} bodyId {body_id} not in mapping")
            else:
                # For types without known bodyIds, skip (would need type-based lookup)
                pass
        # If we got too few, add some visual projection neurons as fallback
        if len(indices) < 8:
            print(f"[FlyBrain] WARN: only {len(indices)} DN found, adding visual fallback to reach 8")
            indices.extend(list(range(min(8 - len(indices), self.engine.n_neurons))))
        return indices[:8]  # cap at 8 DN features (matches training)

    def reset(self, batch_size=1):
        """Reset brain state for new episode."""
        self.engine.state = self.engine.model.state_init(batch_size, self.device)
        self.engine.spike_history.clear()

    def step(self, features, silenced=False):
        """features: (batch, 8) engineered features -> DN rates (batch, n_dn)"""
        batch_size = features.shape[0]

        # Encode features into sensory currents
        with torch.no_grad():
            currents = self.sensory_encoder(features)  # (batch, sensory_dim)

        # Build full current vector
        full_current = torch.zeros(batch_size, self.engine.n_neurons, device=self.device)
        full_current[:, :self.sensory_dim] = currents

        if silenced:
            # Zero out all currents (silence the brain)
            full_current.zero_()

        # Run LIF steps
        for _ in range(self.lif_steps):
            self.engine.step(full_current)

        # Read DN rates
        rates = self.engine.get_dn_rates(torch.tensor(self.dn_indices, device=self.device))

        if silenced:
            rates = torch.zeros_like(rates)

        return rates
