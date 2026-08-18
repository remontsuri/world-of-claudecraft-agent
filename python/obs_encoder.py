"""Shared observation encoder for the headless WoW Classic env.

The real encoder lives in the TypeScript sim (src/sim/obs.ts -> encodeObs)
and is the single source of truth for the (567,) observation vector.
This Python module is a thin convenience wrapper: it pulls obs out of
WoWClassicEnv (which itself gets it from the Node sim bundle) so headless
and browser agents consume the *exact same* vector. We never reimplement
the encoding here -- that would silently diverge the two worlds.
"""

from __future__ import annotations

import numpy as np

from wow_env import WoWClassicEnv


class ObsEncoder:
    """Wraps a WoWClassicEnv and exposes obs_size + action space metadata.

    The obs vector itself is produced by the Node sim (encodeObs in obs.ts),
    so this is purely a pass-through that guarantees headless and browser
    agents see identical shapes and action indices.
    """

    def __init__(self, player_class: str = "warrior", **env_kwargs):
        self.env = WoWClassicEnv(player_class=player_class, **env_kwargs)
        self.obs_size = self.env.observation_space.shape[0]
        self.num_actions = self.env.action_space.n
        self.action_names = self.env.action_names

    def reset(self, seed: int | None = None):
        return self.env.reset(seed=seed)

    def step(self, action: int):
        return self.env.step(action)

    def close(self):
        self.env.close()


if __name__ == "__main__":
    enc = ObsEncoder()
    obs, info = enc.reset(seed=42)
    print(f"obs_size={enc.obs_size} num_actions={enc.num_actions}")
    print(f"obs dtype={obs.dtype} shape={obs.shape}")
    print(f"first 12: {np.round(obs[:12], 3)}")
    enc.close()
