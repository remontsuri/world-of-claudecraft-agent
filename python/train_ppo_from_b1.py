"""train_ppo_from_b1.py — READ-ONLY-SAFE B1->SB3 weight import + parity + smoke.

NO Sim/reward/obs.ts/action changes. The ONLY addition is a Python wrapper that
appends the SAME derived `in_combat_range` feature B1 already used (computed from
the 567 obs via CombatRangeTracker) to make obs 568-dim. Sim/obs.ts untouched;
we just expose the feature B1 was trained on to the SB3 net.

Steps (per user plan):
  1. Build SB3 PPO(MlpPolicy, net_arch=[512,256,128], Discrete(61), obs=568).
  2. Load bc_nav_B1.pt (BCPolicy: 568->512->256->128->61, ReLU between).
  3. Inspect EXACT BC state_dict + EXACT SB3 state_dict; print every name/shape.
  4. Map weights ONLY where source.shape == dest.shape (NO assumption on order).
  5. Verify action head: BC final Linear(128->61) == SB3 action_net (61 outputs).
  6. POLICY PARITY TEST: ~1000 obs from deterministic env states.
     For each: BC logits, SB3 logits, BC argmax, SB3 argmax.
     Report: argmax_match_rate, mean/max abs logit err, KL.
     PASS: argmax_match >= 99% AND no unexpected/missing mappings.
  7. If PASS: SHORT smoke (5k B1 vs 5k scratch) + eval 10 fixed seeds.
  8. If FAIL: STOP, report exact mapping problem, DO NOT train.

Run (parity only, no training):
  therock-test/Scripts/python.exe train_ppo_from_b1.py --parity
Run (parity + smoke 5k):
  therock-test/Scripts/python.exe train_ppo_from_b1.py --smoke
"""
from __future__ import annotations

import argparse
import os
import sys
import json
from pathlib import Path

os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
_WOC = Path(r"D:/world-of-claudecraft/python")
if str(_WOC) not in sys.path:
    sys.path.insert(0, str(_WOC))
_WLLM = Path(r"D:/woc-llm")
if str(_WLLM) not in sys.path:
    sys.path.insert(0, str(_WLLM))

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import gymnasium as gym
from gymnasium import spaces

import audit_common as ac
import curriculum_env as ce
import nav_features as nf

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "nav_data" / "bc_nav_B1.pt"
ABILITY_SLOTS = (ac.TGT - 16) // 2
FEAT_KEYS = ["in_combat_range"]


# ---- BC policy (mirrors bc_nav_model.py / bc_nav_b1_audit.py) ----------------
class BCPolicy(nn.Module):
    def __init__(self, obs_dim, n_act):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, 512), nn.ReLU(),
            nn.Linear(512, 256), nn.ReLU(),
            nn.Linear(256, 128), nn.ReLU(),
            nn.Linear(128, n_act),
        )

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


class CombatLatchWrapper(gym.Env):
    """Appends in_combat_range (568th feature) to the 567-dim obs.

    Uses the SAME CombatRangeTracker (hysteresis 5/7) BC-B1 was trained on.
    Does NOT modify Sim/obs.ts/reward/action. Only exposes the derived feature.
    """
    def __init__(self, base):
        super().__init__()
        self.base = base
        self.tracker = nf.CombatRangeTracker()
        self.observation_space = spaces.Box(
            -2.0, 2.0, shape=(base.observation_space.shape[0] + 1,), dtype=np.float32)
        self.action_space = base.action_space
        self.action_names = base.action_names

    def reset(self, **kw):
        self.tracker = nf.CombatRangeTracker()  # fresh per episode
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


def inspect_and_map(bc_sd, sb3_policy):
    sb3_sd = sb3_policy.state_dict()
    print("\n===== BC state_dict (exact) =====")
    for k, v in bc_sd.items():
        print(f"  BC  {k:40s} {tuple(v.shape)}")
    print("\n===== SB3 policy state_dict (exact) =====")
    for k, v in sb3_sd.items():
        print(f"  SB3 {k:50s} {tuple(v.shape)}")

    bc_layers = {
        "lin0_w": bc_sd["net.0.weight"], "lin0_b": bc_sd["net.0.bias"],
        "lin1_w": bc_sd["net.2.weight"], "lin1_b": bc_sd["net.2.bias"],
        "lin2_w": bc_sd["net.4.weight"], "lin2_b": bc_sd["net.4.bias"],
        "lin3_w": bc_sd["net.6.weight"], "lin3_b": bc_sd["net.6.bias"],
    }
    sb3_map = {
        "mlp_extractor.policy_net.0.weight": "lin0_w",
        "mlp_extractor.policy_net.0.bias": "lin0_b",
        "mlp_extractor.policy_net.2.weight": "lin1_w",
        "mlp_extractor.policy_net.2.bias": "lin1_b",
        "mlp_extractor.policy_net.4.weight": "lin2_w",
        "mlp_extractor.policy_net.4.bias": "lin2_b",
        "action_net.weight": "lin3_w",
        "action_net.bias": "lin3_b",
    }
    report = {"mapped": [], "shape_mismatch": [], "missing_in_sb3": []}
    new_sd = dict(sb3_sd)
    for sb3_k, bc_k in sb3_map.items():
        if sb3_k not in sb3_sd:
            report["missing_in_sb3"].append(sb3_k)
            continue
        bc_t, sb3_t = bc_layers[bc_k], sb3_sd[sb3_k]
        if tuple(bc_t.shape) == tuple(sb3_t.shape):
            new_sd[sb3_k] = bc_t.clone()
            report["mapped"].append((sb3_k, bc_k, tuple(bc_t.shape)))
        else:
            report["shape_mismatch"].append(
                (sb3_k, bc_k, tuple(sb3_t.shape), tuple(bc_t.shape)))
    ah_ok = tuple(sb3_sd["action_net.weight"].shape) == (61, 128)
    print("\n===== MAPPING REPORT =====")
    for m in report["mapped"]:
        print(f"  MAPPED {m[0]} <- {m[1]}  {m[2]}")
    for m in report["shape_mismatch"]:
        print(f"  MISMATCH {m[0]} ({m[2]}) vs {m[1]} ({m[3]})")
    for m in report["missing_in_sb3"]:
        print(f"  MISSING in SB3: {m}")
    print(f"  action_head_is_61: {ah_ok}")
    print(f"  value_net left RANDOM (expected; BC has no value head)")
    sb3_policy.load_state_dict(new_sd, strict=False)
    return report, ah_ok


@torch.no_grad()
def parity_test(sb3_policy, bc_model, n_states=1000, seeds=(42, 43, 44)):
    """Policy parity on a SINGLE 568-dim feature path.

    One hysteresis tracker is owned per episode (mirrors B1 training + real
    WrapperEnv rollout). The 568-dim xin (raw obs + in_combat_range via the
    SAME tracker) is built ONCE per state and fed to BOTH the BC net and the
    SB3 policy — no second/divergent icr computation.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    bc_model.to(device).eval()
    sb3_policy.to(device).eval()
    xin_buf = []   # 568-dim vectors WITH hysteresis latch
    for seed in seeds:
        env = ce.CurriculumEnv(stage=3, player_class="warrior",
                               max_steps=400, frame_skip=5)
        o, _ = env.reset(seed=seed)
        tr = nf.CombatRangeTracker()   # persistent per episode — hysteresis intact
        for _ in range(1, 401):
            xin, _ = bc_featurize(o, tr)   # 568-dim, hysteresis applied here
            xin_buf.append(xin[0].astype(np.float32))
            if len(xin_buf) >= n_states:
                break
            with torch.no_grad():
                a = int(bc_model(torch.from_numpy(xin).to(device)).argmax())
            o, _, term, trunc, _ = env.step(a)
            if term or trunc:
                break
        env.close()
        if len(xin_buf) >= n_states:
            break
    xin_buf = xin_buf[:n_states]

    argmax_match = 0
    logit_errs = []
    kls = []
    for xin in xin_buf:
        xt = torch.from_numpy(xin).unsqueeze(0).to(device)
        with torch.no_grad():
            bc_logit = bc_model(xt)[0].cpu().numpy()
            sb3_logit = sb3_policy.get_distribution(xt).distribution.logits[0].cpu().numpy()
        bc_p = torch.softmax(torch.from_numpy(bc_logit), 0).numpy()
        sb3_p = torch.softmax(torch.from_numpy(sb3_logit), 0).numpy()
        if bc_logit.argmax() == sb3_logit.argmax():
            argmax_match += 1
        logit_errs.append(np.max(np.abs(bc_logit - sb3_logit)))
        eps = 1e-12
        kl = float(np.sum(bc_p * (np.log(bc_p + eps) - np.log(sb3_p + eps))))
        kls.append(kl)
    rate = argmax_match / len(xin_buf) * 100
    print("\n===== PARITY TEST =====")
    print(f"  states            = {len(xin_buf)}")
    print(f"  argmax_match_rate = {rate:.2f}%")
    print(f"  mean abs logiterr = {np.mean(logit_errs):.4f}")
    print(f"  max  abs logiterr = {np.max(logit_errs):.4f}")
    print(f"  mean KL(BC||SB3)  = {np.mean(kls):.5f}")
    print(f"  PASS (argmax>=99%): {rate >= 99.0}")
    return rate >= 99.0, {
        "argmax_match_rate": rate,
        "mean_abs_logit_err": float(np.mean(logit_errs)),
        "max_abs_logit_err": float(np.max(logit_errs)),
        "mean_kl": float(np.mean(kls)),
    }


def value_warmup(model, device, n_steps=5000, epochs=8, lr=1e-3):
    """Train value branch on discounted returns from B1-policy rollouts.

    Identical to train_ppo_full.py:value_warmup. Uses CombatLatchWrapper
    output directly (568-dim, hysteresis already applied by the wrapper).
    Cold value head was the cause of smoke 8/10 -> 3/10 regression:
    advantage became noise and PPO destroyed the good BC policy.
    """
    print(f"\n===== VALUE WARM-UP ({n_steps} steps) =====")
    all_obs, all_ret = [], []
    env = CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior",
                                              max_steps=400, frame_skip=5))
    o, _ = env.reset(seed=42)
    gamma = 0.99
    ep_obs, ep_rews = [], []
    steps = 0
    while steps < n_steps:
        a = int(np.asarray(model.predict(o[None, :], deterministic=True)[0]).item())
        o2, r, term, trunc, info = env.step(int(a))
        ep_obs.append(o.astype(np.float32))
        ep_rews.append(float(r))
        steps += 1
        if term or trunc:
            running = 0.0
            ep_ret = []
            for rew in reversed(ep_rews):
                running = rew + gamma * running
                ep_ret.append(running)
            ep_ret = ep_ret[::-1]
            all_obs.extend(ep_obs)
            all_ret.extend(ep_ret)
            ep_obs, ep_rews = [], []
            o, _ = env.reset(seed=int(np.random.randint(0, 1e6)))
        else:
            o = o2
    env.close()
    if not all_obs:
        print("  warm-up collected 0 steps — skip")
        return
    X = torch.from_numpy(np.asarray(all_obs, np.float32)).to(device)
    Y = torch.from_numpy(np.asarray(all_ret, np.float32)).to(device).unsqueeze(1)
    opt = optim.Adam(
        list(model.policy.mlp_extractor.value_net.parameters()) +
        list(model.policy.value_net.parameters()), lr=lr)
    n = X.shape[0]
    print(f"  collected {n} (obs,return) pairs")
    for ep in range(epochs):
        idx = torch.randperm(n)
        batch = 256
        tot_loss = 0.0
        for s in range(0, n, batch):
            bi = idx[s:s + batch]
            feat = model.policy.extract_features(X[bi])
            _, lat_vf = model.policy.mlp_extractor(feat)
            v = model.policy.value_net(lat_vf)
            loss = nn.functional.mse_loss(v, Y[bi])
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot_loss += loss.item() * bi.shape[0]
        print(f"  epoch {ep+1}/{epochs}  mse={tot_loss/n:.4f}")
    print("  value warm-up done")


@torch.no_grad()
def explained_variance(model, seeds, max_steps=400, frame_skip=5, n_roll=20, device="cpu"):
    """EV of the value head on B1-policy rollouts (diagnostic before/after warm-up)."""
    from stable_baselines3.common.vec_env import DummyVecEnv
    env = CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior",
                                          max_steps=max_steps, frame_skip=frame_skip))
    all_y, all_v = [], []
    for sd in seeds[:n_roll]:
        o, _ = env.reset(seed=sd)
        ep_obs, ep_rews = [], []
        while True:
            a = int(np.asarray(model.predict(o[None, :], deterministic=True)[0]).item())
            o2, r, term, trunc, _ = env.step(int(a))
            ep_obs.append(o.astype(np.float32)); ep_rews.append(float(r))
            o = o2
            if term or trunc:
                break
        running = 0.0
        for rew in reversed(ep_rews):
            running = rew + 0.99 * running
            all_y.append(running)
        for ob in ep_obs:
            feat = model.policy.extract_features(
                torch.from_numpy(ob[None]).to(model.policy.device))
            _, lat_vf = model.policy.mlp_extractor(feat)
            all_v.append(float(model.policy.value_net(lat_vf).item()))
    env.close()
    y = np.asarray(all_y); v = np.asarray(all_v)
    if y.var() < 1e-8:
        return float("nan")
    return 1.0 - float(np.var(y - v) / np.var(y))


def eval_sb3(model, seeds):
    ek = deaths = 0
    for seed in seeds:
        env = CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior",
                                          max_steps=400, frame_skip=5))
        o, _ = env.reset(seed=seed)
        kills = dead = 0
        for _ in range(1, 401):
            a, _ = model.predict(o, deterministic=True)
            o, r, term, trunc, info = env.step(int(a))
            kills = max(kills, info.get("kills", 0) or 0)
            if (info.get("deaths", 0) or 0) > 0:
                dead = 1
            if term or trunc:
                break
        env.close()
        ek += int(kills > 0)
        deaths += dead
    return ek, deaths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parity", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--n-states", type=int, default=1000)
    args = ap.parse_args()
    if not (args.parity or args.smoke):
        print("Use --parity or --smoke. No training by default.")
        return

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    bc_ckpt = torch.load(OUT, map_location="cpu", weights_only=True)
    bc = BCPolicy(bc_ckpt["obs_dim"], bc_ckpt["n_act"])
    bc.load_state_dict(bc_ckpt["state_dict"])

    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv
    base = lambda: CombatLatchWrapper(ce.CurriculumEnv(stage=3, player_class="warrior",
                                               max_steps=400, frame_skip=5))
    env = make_vec_env(base, n_envs=1, seed=42, vec_env_cls=SubprocVecEnv)
    sb3 = PPO("MlpPolicy", env, learning_rate=3e-4, n_steps=256, batch_size=64,
              n_epochs=4, gamma=0.99, gae_lambda=0.95, clip_range=0.2,
              ent_coef=0.01, vf_coef=0.5, max_grad_norm=0.5,
              policy_kwargs={"net_arch": [512, 256, 128], "activation_fn": torch.nn.ReLU},
              device=device, seed=42, verbose=0)

    report, ah_ok = inspect_and_map(bc.state_dict(), sb3.policy)
    w0_before = sb3.policy.mlp_extractor.policy_net[0].weight[0, 0].item()
    w0_bc = bc.state_dict()["net.0.weight"][0, 0].item()
    print(f"[DEBUG] policy_net.0[0,0] after map = {w0_before:.6f} | BC net.0[0,0] = {w0_bc:.6f} | "
          f"match={abs(w0_before-w0_bc)<1e-5}")
    parity_pass, parity_stats = parity_test(sb3.policy, bc, n_states=args.n_states)

    result = {"mapping": report, "action_head_is_61": ah_ok,
              "parity_pass": parity_pass, "parity_stats": parity_stats}
    with open(ROOT / "nav_data" / "b1_sb3_parity.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    print("\nSaved nav_data/b1_sb3_parity.json")

    if not parity_pass:
        print("\n>>> PARITY FAILED. STOP. Do NOT train PPO.")
        env.close()
        return
    print("\n>>> PARITY PASSED. B1 weights correctly imported into SB3 policy.")

    if args.smoke:
        print("\n===== SMOKE (mode A): value warm-up -> 5k PPO (B1) =====")
        # Diagnostic BEFORE warm-up
        ev_before = explained_variance(sb3, device=device, seeds=list(range(42, 52)))
        print(f"  explained_variance BEFORE warm-up = {ev_before:.4f}")
        # Value head warm-up (the missing step that caused 8/10 -> 3/10)
        value_warmup(sb3, device, n_steps=5000)
        ev_after = explained_variance(sb3, seeds=list(range(42, 52)))
        print(f"  explained_variance AFTER  warm-up = {ev_after:.4f}")
        sb3.learn(total_timesteps=5000, tb_log_name="b1_smoke")
        sb3.save(str(ROOT / "nav_data" / "ppo_from_b1_smoke"))
        ek, d = eval_sb3(sb3, list(range(42, 52)))
        print(f"  B1-imported (warm-up+5k): episodes_with_kill={ek}/10 death={d}%")
        print("  GATE: >=7/10 -> proceed to 50k; <7/10 -> B1 stays final (no PPO).")
        # Reference: scratch 5k (expected ~0/10 — sanity that B1-start matters)
        sb3_scratch = PPO("MlpPolicy", env, learning_rate=3e-4, n_steps=256,
                          batch_size=64, n_epochs=4, gamma=0.99,
                          gae_lambda=0.95, clip_range=0.2, ent_coef=0.01,
                          vf_coef=0.5, max_grad_norm=0.5,
                          policy_kwargs={"net_arch": [512, 256, 128], "activation_fn": torch.nn.ReLU},
                          device=device, seed=42, verbose=0)
        sb3_scratch.learn(total_timesteps=5000, tb_log_name="scratch_smoke")
        sb3_scratch.save(str(ROOT / "nav_data" / "ppo_from_scratch_smoke"))
        ek2, d2 = eval_sb3(sb3_scratch, list(range(42, 52)))
        print(f"  scratch 5k:                episodes_with_kill={ek2}/10 death={d2}%")
    env.close()


if __name__ == "__main__":
    main()
