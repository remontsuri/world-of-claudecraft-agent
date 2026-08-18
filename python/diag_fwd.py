"""diag_fwd.py — локализует расхождение BC vs SB3 при одинаковых весах/входе."""
import os, sys
from pathlib import Path
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
_ROOT = Path(r"D:/world-of-claudecraft/python")
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, r"D:/woc-llm")

import numpy as np
import torch
import torch.nn as nn
import audit_common as ac
import curriculum_env as ce
import nav_features as nf

ABILITY_SLOTS = (ac.TGT - 16) // 2
FEAT_KEYS = ["in_combat_range"]


class BCPolicy(nn.Module):
    def __init__(self, obs_dim, n_act):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, 512), nn.ReLU(),
            nn.Linear(512, 256), nn.ReLU(),
            nn.Linear(256, 128), nn.ReLU(),
            nn.Linear(128, n_act))

    def forward(self, x):
        return self.net(x)


def bc_featurize(obs, tracker):
    target, mob = nf.decode_nav_obs(obs, ABILITY_SLOTS)
    icr = tracker.update(bool(target["has"]), target["dist"])
    nfobj = nf.make_nav_features(
        mob_dist=(mob["dist"] if mob else nf.MOB_SAT * nf.DIST_SCALE),
        mob_sin=(mob["sin"] if mob else 0.0),
        mob_cos=(mob["cos"] if mob else 0.0),
        target_has=bool(target["has"]), target_dist=target["dist"],
        target_sin=target["sin"], target_cos=target["cos"],
        in_combat_range=icr)
    feats = np.asarray(
        [[float(icr if k == "in_combat_range" else getattr(nfobj, k))
          for k in FEAT_KEYS]], dtype=np.float32)
    return np.concatenate([np.asarray(obs, np.float32)[None], feats], axis=1), icr


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(_ROOT / "nav_data" / "bc_nav_B1.pt", map_location="cpu", weights_only=True)
    bc = BCPolicy(ckpt["obs_dim"], ckpt["n_act"]).to(device)
    bc.load_state_dict(ckpt["state_dict"])
    bc.eval()

    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.vec_env import SubprocVecEnv

    from train_ppo_from_b1 import CombatLatchWrapper, inspect_and_map

    base = lambda: CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior",
                                                       max_steps=400, frame_skip=5))
    env = make_vec_env(base, n_envs=1, seed=42, vec_env_cls=SubprocVecEnv)
    sb3 = PPO("MlpPolicy", env, learning_rate=3e-4, n_steps=256, batch_size=64,
              n_epochs=4, gamma=0.99, gae_lambda=0.95, clip_range=0.2,
              ent_coef=0.01, vf_coef=0.5, max_grad_norm=0.5,
              policy_kwargs={"net_arch": [512, 256, 128]},
              device=device, seed=42, verbose=0)
    inspect_and_map(bc.state_dict(), sb3.policy)
    env.close()

    # collect 10 xin with ONE tracker per episode
    xin_buf = []
    for seed in (42, 43):
        e = ce.CurriculumEnv(stage=3, player_class="warrior", max_steps=400, frame_skip=5)
        o, _ = e.reset(seed=seed)
        tr = nf.CombatRangeTracker()
        for _ in range(1, 401):
            xin, _ = bc_featurize(o, tr)
            xin_buf.append(xin[0].astype(np.float32))
            a = int(bc(torch.from_numpy(xin).to(device)).argmax())
            o, _, term, trunc, _ = e.step(a)
            if term or trunc:
                break
        e.close()
        if len(xin_buf) >= 10:
            break
    xin_buf = xin_buf[:10]

    print(f"\n{'#':>2} | {'BC':>3} | {'SB3man':>3} | {'SB3gd':>3} | note")
    for i, xin in enumerate(xin_buf):
        xt = torch.from_numpy(xin).unsqueeze(0).to(device)
        with torch.no_grad():
            bc_l = bc(xt)[0].cpu().numpy()
            feat = sb3.policy.extract_features(xt)
            lat = sb3.policy.mlp_extractor(feat)[0]
            sb3man_l = sb3.policy.action_net(lat)[0].cpu().numpy()
            sb3gd_l = sb3.policy.get_distribution(xt).distribution.logits[0].cpu().numpy()
        bca, ma, ga = bc_l.argmax(), sb3man_l.argmax(), sb3gd_l.argmax()
        note = "" if (bca == ma == ga) else " <-- DIVERGE"
        print(f"{i:2} | {bca:3} | {ma:3} | {ga:3} | {note}")
        if i == 0:
            # print full logits for first state
            print("   BC   :", np.round(bc_l[:8], 3), "...")
            print("   SB3mn:", np.round(sb3man_l[:8], 3), "...")
            print("   SB3gd:", np.round(sb3gd_l[:8], 3), "...")
            print("   corr BC vs SB3man:", np.corrcoef(bc_l, sb3man_l)[0, 1])
            print("   corr BC vs SB3gd :", np.corrcoef(bc_l, sb3gd_l)[0, 1])
            # check weights layer-by-layer
            sd_bc = bc.state_dict()
            pe = sb3.policy.mlp_extractor.policy_net
            print("   L0 w[0,0] BC=%.6f SB3=%.6f" % (sd_bc["net.0.weight"][0,0].item(), pe[0].weight[0,0].item()))
            print("   L0 b[0]   BC=%.6f SB3=%.6f" % (sd_bc["net.0.bias"][0].item(), pe[0].bias[0].item()))
            print("   L2 w[0,0] BC=%.6f SB3=%.6f" % (sd_bc["net.2.weight"][0,0].item(), pe[2].weight[0,0].item()))
            print("   L4 w[0,0] BC=%.6f SB3=%.6f" % (sd_bc["net.4.weight"][0,0].item(), pe[4].weight[0,0].item()))
            an = sb3.policy.action_net
            print("   AN w[0,0] BC=%.6f SB3=%.6f" % (sd_bc["net.6.weight"][0,0].item(), an.weight[0,0].item()))
            print("   extract_features == xt? ", torch.allclose(feat, xt))


if __name__ == "__main__":
    main()
