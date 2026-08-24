"""DIAGNOSTIC ONLY. Why parity fails at 75% even with (512,568) match?

Compares SB3's REAL forward chain (policy(obs)) against:
  (A) our BC forward (568 input)
  (B) manual extract_features -> mlp_extractor -> action_net (568 input)
Goal: find where SB3 diverges from BC despite identical weights.
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


class CombatLatchWrapper(gym.Env):
    def __init__(self, base):
        super().__init__()
        self.base = base
        self.tracker = nf.CombatRangeTracker()
        self.observation_space = spaces.Box(-2.0, 2.0,
            shape=(base.observation_space.shape[0] + 1,), dtype=np.float32)
        self.action_space = base.action_space
        self.action_names = base.action_names

    def reset(self, **kw):
        self.tracker = nf.CombatRangeTracker()
        o, info = self.base.reset(**kw)
        t, _ = nf.decode_nav_obs(o, ABILITY_SLOTS)
        latch = self.tracker.update(bool(t["has"]), t["dist"])
        return np.concatenate([o, [1.0 if latch else 0.0]]).astype(np.float32), info

    def step(self, action):
        o, r, term, trunc, info = self.base.step(action)
        t, _ = nf.decode_nav_obs(o, ABILITY_SLOTS)
        latch = self.tracker.update(bool(t["has"]), t["dist"])
        return np.concatenate([o, [1.0 if latch else 0.0]]).astype(np.float32), \
            r, term, trunc, info

    def close(self):
        self.base.close()


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    bc = BCPolicy(568, 61)
    bc.load_state_dict(torch.load(OUT, map_location="cpu", weights_only=True)["state_dict"])
    bc.to(device).eval()

    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.vec_env import SubprocVecEnv
    env = make_vec_env(lambda: CombatLatchWrapper(ce.CurriculumEnv(
        stage=3, player_class="warrior", max_steps=400, frame_skip=5)),
        n_envs=1, seed=42, vec_env_cls=SubprocVecEnv)
    sb3 = PPO("MlpPolicy", env, policy_kwargs={"net_arch": [512, 256, 128]},
              device=device, seed=42, verbose=0)
    sd = sb3.policy.state_dict()
    bc_sd = bc.state_dict()
    for sb3k, bck in [("mlp_extractor.policy_net.0","net.0"),
                      ("mlp_extractor.policy_net.2","net.2"),
                      ("mlp_extractor.policy_net.4","net.4"),
                      ("action_net","net.6")]:
        sd[sb3k+".weight"] = bc_sd[bck+".weight"].clone()
        sd[sb3k+".bias"] = bc_sd[bck+".bias"].clone()
    sb3.policy.load_state_dict(sd, strict=False)
    sb3.policy.to(device).eval()

    e = CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior",
                                            max_steps=400, frame_skip=5))
    o568, _ = e.reset(seed=42)
    t, _ = nf.decode_nav_obs(o568[:567], ABILITY_SLOTS)
    # BC expects 568
    bc_in = torch.from_numpy(o568).unsqueeze(0).to(device)
    # SB3 expects 567 (its features_extractor handles obs); but our wrapper gives 568.
    # SB3 policy.forward internally: obs -> extract_features -> mlp_extractor -> action_net
    sb3_in = torch.from_numpy(o568).unsqueeze(0).to(device)  # 568 (wrapper output)

    with torch.no_grad():
        bc_logit = bc(bc_in)[0].cpu().numpy()
        # REAL SB3 forward
        sb3_acts, sb3_vals, sb3_lp = sb3.policy(sb3_in)
        sb3_real_logit = sb3.policy.get_distribution(sb3_in).distribution.logits[0].cpu().numpy()
        # manual
        feats = sb3.policy.extract_features(sb3_in)
        lat = sb3.policy.mlp_extractor(feats)
        manual_logit = sb3.policy.action_net(lat[0])[0].cpu().numpy()

    print("BC argmax          :", int(np.argmax(bc_logit)))
    print("SB3 real forward   :", int(torch.argmax(sb3_acts).item()))
    print("SB3 dist logits    :", int(np.argmax(sb3_real_logit)))
    print("Manual extract->act:", int(np.argmax(manual_logit)))
    print("\ncorr BC vs SB3-real  :", np.corrcoef(bc_logit, sb3_real_logit)[0,1])
    print("corr BC vs Manual   :", np.corrcoef(bc_logit, manual_logit)[0,1])
    print("corr SB3-real vs Man:", np.corrcoef(sb3_real_logit, manual_logit)[0,1])
    print("\nBC logit[:5]      :", np.round(bc_logit[:5], 3))
    print("SB3 real logit[:5] :", np.round(sb3_real_logit[:5], 3))
    print("Manual logit[:5]   :", np.round(manual_logit[:5], 3))
    env.close(); e.close()


if __name__ == "__main__":
    main()
