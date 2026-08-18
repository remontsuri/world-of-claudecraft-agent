"""Phase D basis proof (safe): MaskablePPO learns on a heal-only masked env.
Forces action_masks to ONLY heal (index 7) so the agent never triggers farm
navigation (the known server-crash gap). Proves the masked PPO pipeline runs
end-to-end (init + learn + masked predict) without crashing the node server.
Farm/loot navigation stability is a SEPARATE gap (see TRAINING.md).
"""
import os, numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.utils import get_action_masks
from hierarchical_env import HierarchicalWoWEnv, make_hl_env, N_SKILLS, SKILLS

# force only heal maskable
def _heal_only_mask(self):
    m = np.zeros(N_SKILLS, dtype=bool)
    m[7] = True
    return m
HierarchicalWoWEnv.action_masks = _heal_only_mask

out = "models/hl_ppo_heal_only"
os.makedirs(out, exist_ok=True)
env = make_hl_env(player_class="warrior", max_steps=200, seed=0)
model = MaskablePPO("MlpPolicy", env, verbose=0, device="cuda",
                    n_steps=64, batch_size=32, n_epochs=2, gamma=0.95)
model.learn(total_timesteps=64)   # 1 rollout on heal-only
obs, _ = env.reset(seed=1)
a, _ = model.predict(obs, action_masks=get_action_masks(env), deterministic=True)
assert int(a) == 7, f"masked predict must pick heal(7), got {int(a)}"
obs, r, term, trunc, _ = env.step(int(a))
print(f"PPO heal-only: learn OK, masked predict={SKILLS[int(a)]}({int(a)}), reward={float(r):.3f}")
env.close()
print("PHASE D BASIS PROVEN (heal-only). Farm/loot nav stability = separate gap.")
