"""PPO agent wrapper for World of Claudecraft — BC-B1 fine-tune variant.

Loads the SB3 PPO model trained from BC-B1 (train_ppo_full.py), which expects
a 568-dim obs: the original 567 from encodeObs PLUS the derived in_combat_range
feature (hysteresis latch via CombatRangeTracker). The browser bridge sends the
567-dim obs; this wrapper reconstructs the 568th feature with a persistent
tracker so the online input matches training exactly.

Run:  ppo_server.py --model nav_data/ppo_from_b1_full.zip
Bridge: debug_agent_cdp.ts --mode ppo --ppo-url http://127.0.0.1:5000/predict
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
# audit_common.py lives in D:/woc-llm (separate training home), not under python/
_WOC_LLM = os.path.normpath(os.path.join(_ROOT, "..", "..", "woc-llm"))
for _p in (_ROOT, _WOC_LLM):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np

import audit_common as ac
import nav_features as nf

ABILITY_SLOTS = (ac.TGT - 16) // 2


class PPOAgentB1:
    def __init__(self, model_path: str, device: str = "auto"):
        from stable_baselines3 import PPO
        self.model = PPO.load(model_path, device=device)
        self.obs_size = int(self.model.observation_space.shape[0])  # 568
        self.num_actions = int(self.model.action_space.n)
        # persistent hysteresis tracker, one per (online) episode-stream
        self.tracker = nf.CombatRangeTracker()

    def reset_tracker(self):
        """Call on a new episode / zone change so the latch doesn't carry over."""
        self.tracker = nf.CombatRangeTracker()

    def decide(self, obs: np.ndarray, target: dict | None = None) -> tuple[int, str]:
        try:
            arr = np.asarray(obs, dtype=np.float32).reshape(-1)
            if arr.shape[0] == 567:
                # reconstruct the 568th feature the same way training did
                target_dec, _ = nf.decode_nav_obs(arr, ABILITY_SLOTS)
                icr = self.tracker.update(bool(target_dec["has"]), target_dec["dist"])
                arr = np.concatenate([arr, [1.0 if icr else 0.0]]).astype(np.float32)
            elif arr.shape[0] != 568:
                raise ValueError(f"expected 567 or 568, got {arr.shape[0]}")
            arr = arr.reshape(1, -1)
            action, _ = self.model.predict(arr, deterministic=True)
            action = int(np.asarray(action).reshape(-1)[0])
            return action, "PPO-B1"
        except Exception:
            import traceback
            traceback.print_exc()
            raise
