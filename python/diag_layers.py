"""diag_layers.py — пошаговое сравнение активаций BC vs SB3 (DummyVecEnv, без spawn)."""
import os, sys
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
sys.path.insert(0, r"D:/world-of-claudecraft/python")
sys.path.insert(0, r"D:/woc-llm")

import torch, numpy as np
import audit_common as ac, curriculum_env as ce, nav_features as nf
from train_ppo_from_b1 import BCPolicy, bc_featurize

ABILITY_SLOTS = (ac.TGT - 16) // 2
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

ckpt = torch.load(r"D:/world-of-claudecraft/python/nav_data/bc_nav_B1.pt", map_location="cpu", weights_only=True)
bc = BCPolicy(ckpt["obs_dim"], ckpt["n_act"]).to(device)
bc.load_state_dict(ckpt["state_dict"]); bc.eval()

from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import DummyVecEnv

from train_ppo_from_b1 import CombatLatchWrapper
base = lambda: CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior", max_steps=400, frame_skip=5))
env = make_vec_env(base, n_envs=1, seed=42, vec_env_cls=DummyVecEnv)
sb3 = PPO("MlpPolicy", env, learning_rate=3e-4, n_steps=256, batch_size=64,
          n_epochs=4, gamma=0.99, gae_lambda=0.95, clip_range=0.2,
          ent_coef=0.01, vf_coef=0.5, max_grad_norm=0.5,
          policy_kwargs={"net_arch": [512, 256, 128]}, device=device, seed=42, verbose=0)

bc_sd = bc.state_dict()
sb3_sd = sb3.policy.state_dict()
mapping = {
    "mlp_extractor.policy_net.0.weight": "net.0.weight",
    "mlp_extractor.policy_net.0.bias": "net.0.bias",
    "mlp_extractor.policy_net.2.weight": "net.2.weight",
    "mlp_extractor.policy_net.2.bias": "net.2.bias",
    "mlp_extractor.policy_net.4.weight": "net.4.weight",
    "mlp_extractor.policy_net.4.bias": "net.4.bias",
    "action_net.weight": "net.6.weight",
    "action_net.bias": "net.6.bias",
}
new_sd = dict(sb3_sd)
for k, v in mapping.items():
    new_sd[k] = bc_sd[v].clone()
sb3.policy.load_state_dict(new_sd, strict=False)
env.close()

e = ce.CurriculumEnv(stage=3, player_class="warrior", max_steps=400, frame_skip=5)
o, _ = e.reset(seed=42)
tr = nf.CombatRangeTracker()
xin, _ = bc_featurize(o, tr)
xt = torch.from_numpy(xin[0].astype(np.float32)).unsqueeze(0).to(device)

with torch.no_grad():
    h_bc = xt
    for layer in bc.net:
        h_bc = layer(h_bc)
    bc_logit = h_bc[0].cpu().numpy()

    feat = sb3.policy.extract_features(xt)
    print("extract_features == xt:", torch.allclose(feat, xt))
    pe = sb3.policy.mlp_extractor.policy_net
    h = feat
    print("\n--- SB3 policy_net layers ---")
    for i, layer in enumerate(pe):
        h = layer(h)
        print(f"  [{i}] {layer.__class__.__name__:6s} out_mean={float(h.abs().mean()):.4f}")
    lat = h
    sb3_man_logit = sb3.policy.action_net(lat)[0].cpu().numpy()
    sb3_gd_logit = sb3.policy.get_distribution(xt).distribution.logits[0].cpu().numpy()

print("\nBC  logit[0:5]:", np.round(bc_logit[:5], 3))
print("SB3m logit[0:5]:", np.round(sb3_man_logit[:5], 3))
print("SB3g logit[0:5]:", np.round(sb3_gd_logit[:5], 3))
print("\nBC argmax:", bc_logit.argmax(), "SB3m:", sb3_man_logit.argmax(), "SB3g:", sb3_gd_logit.argmax())
print("corr BC vs SB3m:", np.corrcoef(bc_logit, sb3_man_logit)[0, 1])
# intermediate: after L0
print("\nL0(568->512) out[0:3] BC:", np.round(bc.net[0](xt)[0, :3].cpu().numpy(), 4))
print("L0(568->512) out[0:3] SB3:", np.round(pe[0](feat)[0, :3].cpu().numpy(), 4))
print("L0 w[0,0] BC=%.6f SB3=%.6f" % (bc_sd['net.0.weight'][0, 0].item(), pe[0].weight[0, 0].item()))
print("L2(256->128) w[0,0] BC=%.6f SB3=%.6f" % (bc_sd['net.2.weight'][0, 0].item(), pe[2].weight[0, 0].item()))
print("AN w[0,0] BC=%.6f SB3=%.6f" % (bc_sd['net.6.weight'][0, 0].item(), sb3.policy.action_net.weight[0, 0].item()))
print("AN in_features SB3:", sb3.policy.action_net.in_features, "BC L3 in:", 128)
