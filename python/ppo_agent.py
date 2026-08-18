"""PPO agent wrapper for World of Claudecraft.

Loads a stable-baselines3 policy trained against the headless env and
exposes the same `decide(obs) -> action_index` interface as
ScriptedController, so the Agent Bridge can swap one for the other
without touching the game-facing code.

The model was trained on the (567,) obs from encodeObs (obs.ts) -- the
SAME vector the browser bridge produces, which is why a single
obs_encoder keeps headless and browser trajectories compatible.
"""

from __future__ import annotations

import numpy as np


class PPOAgent:
    def __init__(self, model_path: str, device: str = "auto"):
        try:
            from stable_baselines3 import PPO
        except ImportError as e:  # pragma: no cover
            raise ImportError("pip install stable-baselines3") from e
        self.model = PPO.load(model_path, device=device)
        self.obs_size = self.model.observation_space.shape[0]
        self.num_actions = self.model.action_space.n

    def decide(self, obs: np.ndarray, target: dict | None = None) -> tuple[int, str]:
        # target arg kept for interface symmetry with ScriptedController; PPO
        # reads everything it needs from obs.
        arr = np.asarray(obs, dtype=np.float32).reshape(1, -1)
        action, _ = self.model.predict(arr, deterministic=True)
        return int(action), "PPO"
