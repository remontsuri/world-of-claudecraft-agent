"""diag_struct.py — печатает структуру BC vs SB3 и shapes промежуточных тензоров."""
import os, sys
from pathlib import Path
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
_ROOT = Path(r"D:/world-of-claudecraft/python")
sys.path.insert(0, str(_ROOT)); sys.path.insert(0, r"D:/woc-llm")
import torch, numpy as np
import audit_common as ac, curriculum_env as ce, nav_features as nf
from train_ppo_from_b1 import BCPolicy, CombatLatchWrapper, inspect_and_map
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv

ABILITY_SLOTS = (ac.TGT - 16) // 2
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
ckpt = torch.load(_ROOT / "nav_data" / "bc_nav_B1.pt", map_location="cpu", weights_only=True)
bc = BCPolicy(ckpt["obs_dim"], ckpt["n_act"]).to(device)
bc.load_state_dict(ckpt["state_dict"]); bc.eval()

base = lambda: CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior", max_steps=400, frame_skip=5))
env = make_vec_env(base, n_envs=1, seed=42, vec_env_cls=SubprocVecEnv)
sb3 = PPO("MlpPolicy", env, learning_rate=3e-4, n_steps=256, batch_size=64,
          n_epochs=4, gamma=0.99, gae_lambda=0.95, clip_range=0.2,
          ent_coef=0.01, vf_coef=0.5, max_grad_norm=0.5,
          policy_kwargs={"net_arch": [512, 256, 128]}, device=device, seed=42, verbose=0)
inspect_and_map(bc.state_dict(), sb3.policy)
env.close()

print("\n--- BC net structure ---")
print(bc.net)
print("\n--- SB3 mlp_extractor ---")
print(sb3.policy.mlp_extractor)
print("\n--- SB3 action_net ---")
print(sb3.policy.action_net)

# one state
e = ce.CurriculumEnv(stage=3, player_class="warrior", max_steps=400, frame_skip=5)
o, _ = e.reset(seed=42)
tr = nf.CombatRangeTracker()
from train_ppo_from_b1 import bc_featurize
xin, _ = bc_featurize(o, tr)
xt = torch.from_numpy(xin[0].astype(np.float32)).unsqueeze(0).to(device)
feat = sb3.policy.extract_features(xt)
out = sb3.policy.mlp_extractor(feat)
print("\n--- shapes ---")
print("xt       :", tuple(xt.shape))
print("feat     :", tuple(feat.shape))
for i, t in enumerate(out):
    print(f"mlp_extr[{i}]:", tuple(t.shape))
print("action_net(out[1]).shape     :", tuple(sb3.policy.action_net(out[1]).shape))
print("action_net(out[0]).shape     :", tuple(sb3.policy.action_net(out[0]).shape) if out[0].shape[1]==128 else "N/A (not 128)")
# BC intermediate
print("\n--- BC intermediate (with final ReLU) ---")
h = xt
for layer in bc.net:
    h = layer(h)
    print("  after", layer.__class__.__name__, "->", tuple(h.shape))
