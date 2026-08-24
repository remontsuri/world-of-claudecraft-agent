"""DIAGNOSTIC ONLY (no training). Why does parity fail at 75%?

Checks SB3 ActorCriticPolicy forward chain vs our manual BC forward, to find
where the semantic gap is. Read-only.
"""
import os, sys
from pathlib import Path
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
for p in [r"D:/world-of-claudecraft/python", r"D:/woc-llm"]:
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np
import torch
import torch.nn as nn
import gymnasium as gym
from gymnasium import spaces
import audit_common as ac
import curriculum_env as ce
import nav_features as nf

ABILITY_SLOTS = (ac.TGT - 16) // 2
ROOT = Path(r"D:/world-of-claudecraft/python")
OUT = ROOT / "nav_data" / "bc_nav_B1.pt"


class BCPolicy(nn.Module):
    def __init__(self, o, a):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(o, 512), nn.ReLU(), nn.Linear(512, 256),
                                  nn.ReLU(), nn.Linear(256, 128), nn.ReLU(),
                                  nn.Linear(128, a))

    def forward(self, x):
        return self.net(x)


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    bc = BCPolicy(568, 61)
    bc.load_state_dict(torch.load(OUT, map_location="cpu", weights_only=True)["state_dict"])
    bc.to(device).eval()

    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.vec_env import SubprocVecEnv
    env = make_vec_env(lambda: ce.CurriculumEnv(stage=3, player_class="warrior",
                                                max_steps=400, frame_skip=5),
                       n_envs=1, seed=42, vec_env_cls=SubprocVecEnv)
    sb3 = PPO("MlpPolicy", env, policy_kwargs={"net_arch": [512, 256, 128]},
              device=device, seed=42, verbose=0)
    # import BC weights
    sd = sb3.policy.state_dict()
    bc_sd = bc.state_dict()
    sd["mlp_extractor.policy_net.0.weight"] = bc_sd["net.0.weight"].clone()
    sd["mlp_extractor.policy_net.0.bias"] = bc_sd["net.0.bias"].clone()
    sd["mlp_extractor.policy_net.2.weight"] = bc_sd["net.2.weight"].clone()
    sd["mlp_extractor.policy_net.2.bias"] = bc_sd["net.2.bias"].clone()
    sd["mlp_extractor.policy_net.4.weight"] = bc_sd["net.4.weight"].clone()
    sd["mlp_extractor.policy_net.4.bias"] = bc_sd["net.4.bias"].clone()
    sd["action_net.weight"] = bc_sd["net.6.weight"].clone()
    sd["action_net.bias"] = bc_sd["net.6.bias"].clone()
    sb3.policy.load_state_dict(sd, strict=False)
    sb3.policy.to(device).eval()

    # collect one obs
    e = ce.CurriculumEnv(stage=3, player_class="warrior", max_steps=400, frame_skip=5)
    o, _ = e.reset(seed=42)
    t, m = nf.decode_nav_obs(o, ABILITY_SLOTS)
    icr = 1.0 if (t["has"] and t["dist"] <= nf.MELEE_YD) else 0.0
    obs568 = np.concatenate([np.asarray(o, np.float32), [icr]])

    # (A) BC raw forward
    with torch.no_grad():
        bc_logit = bc(torch.from_numpy(obs568).unsqueeze(0).to(device))[0].cpu().numpy()

    # (B) SB3 full policy forward (what PPO actually uses)
    with torch.no_grad():
        # SB3 obs must be 567 (it has its own features_extractor that appends nothing)
        t_ = torch.from_numpy(np.asarray(o, np.float32)).unsqueeze(0).to(device)
        sb3_full, _ = sb3.policy.predict_values(t_) if False else (None, None)
        # correct: use sb3.policy(obs) -> actions via forward
        sb3_actions, sb3_values, sb3_logp = sb3.policy(torch.as_tensor(
            np.asarray(o, np.float32), dtype=torch.float32, device=device).unsqueeze(0))
        sb3_action_dist = sb3.policy.get_distribution(torch.as_tensor(
            np.asarray(o, np.float32), dtype=torch.float32, device=device).unsqueeze(0))
        sb3_logit_full = sb3_action_dist.distribution.logits[0].cpu().numpy()

    # (C) manual: extract_features(567) -> mlp_extractor -> action_net
    with torch.no_grad():
        feats = sb3.policy.extract_features(torch.as_tensor(
            np.asarray(o, np.float32), dtype=torch.float32, device=device).unsqueeze(0))
        print("extract_features out shape:", tuple(feats.shape), "(expect 567 or 568?)")
        lat = sb3.policy.mlp_extractor(feats)
        print("mlp_extractor returns tuple len:", len(lat), "actor shape:", tuple(lat[0].shape))
        manual_logit = sb3.policy.action_net(lat[0])[0].cpu().numpy()

    print("\n--- argmax compare ---")
    print("BC argmax        :", int(np.argmax(bc_logit)))
    print("SB3 full forward :", int(torch.argmax(sb3_actions).item()))
    print("SB3 dist logits  :", int(np.argmax(sb3_logit_full)))
    print("Manual (567)     :", int(np.argmax(manual_logit)))

    print("\n--- logit correlation BC vs each ---")
    print("BC vs SB3-full   :", np.corrcoef(bc_logit, sb3_logit_full)[0, 1])
    print("BC vs Manual567  :", np.corrcoef(bc_logit, manual_logit)[0, 1])

    print("\n--- key question: does SB3 expect 567 or 568 at extract_features? ---")
    try:
        with torch.no_grad():
            feats568 = sb3.policy.extract_features(torch.from_numpy(
                obs568).unsqueeze(0).to(device))
        print("extract_features(568) OK shape:", tuple(feats568.shape))
    except Exception as ex:
        print("extract_features(568) FAILS:", str(ex)[:120])
    env.close()
    e.close()


if __name__ == "__main__":
    main()
