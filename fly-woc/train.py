"""Train the fly-brain readout on world-of-claudecraft with PPO, then evaluate
it against the full control battery and export every rollout as evidence.

Architecture (identical pattern in Fly Dino v2, fly-craftax, FLYT3):
    obs -> engineered features -> FROZEN MaleCNS circuit -> DN activities
        -> trainable readout (actor/critic) -> Discrete(61) action
The circuit, drive mapping and dynamics are never trained.

Controls (reference: FLY_BRAIN_REFERENCE.md section 6):
  fly            trained readout on circuit activity
  fly-silenced   same trained readout, circuit activity zeroed
  fly-untrained  same architecture, untrained init (same seed)
  mlp            same PPO budget on raw obs, no brain (negative control)
  random         uniform actions
  openloop       forward/attack alternation (fly-craftax 'alternate' control)

Usage:
  python3 train.py --policy fly --updates 400 --seed 20260914
  python3 train.py --policy mlp --updates 400 --seed 20260914
  python3 train.py --eval-only                # benchmark from saved params
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

# Path to the world-of-claudecraft checkout containing python/wow_env.py.
# Override with WOC_PYTHON_PATH (e.g. D:/world-of-claudecraft/python on Windows).
WOC_PYTHON = os.environ.get("WOC_PYTHON_PATH", "/home/user/repos/woc-game/python")
sys.path.insert(0, WOC_PYTHON)
from wow_env import WoWClassicEnv  # noqa: E402

from fly_brain import FlyBrain, extract_features  # noqa: E402
from agent import FlyBrainReadout, MLPControl  # noqa: E402

OUT = Path(__file__).parent / "outputs"


# ------------------------------------------------------------------ env batch
class EnvBatch:
    def __init__(self, n: int, max_steps: int, player_class: str, rewards: dict | None = None):
        self.envs = [WoWClassicEnv(player_class=player_class, max_steps=max_steps, rewards=rewards)
                     for _ in range(n)]
        self.n = n
        self.obs = np.zeros((n, self.envs[0].observation_space.shape[0]), np.float32)
        self.ep_return = np.zeros(n); self.ep_len = np.zeros(n, np.int64)
        self.last_infos = [{} for _ in range(n)]
        self.finished: list[dict] = []

    def reset(self, seeds: list[int]):
        for i, env in enumerate(self.envs):
            self.obs[i], _ = env.reset(seed=seeds[i])
        self.ep_return[:] = 0; self.ep_len[:] = 0; self.finished.clear()

    def step(self, actions: np.ndarray):
        dones = np.zeros(self.n, bool)
        rewards = np.zeros(self.n, np.float32)
        for i, env in enumerate(self.envs):
            o, r, term, trunc, info = env.step(int(actions[i]))
            self.obs[i] = o
            rewards[i] = r
            self.ep_return[i] += r; self.ep_len[i] += 1
            self.last_infos[i] = info
            if term or trunc:
                dones[i] = True
                self.finished.append({
                    "steps": int(self.ep_len[i]), "reward": round(float(self.ep_return[i]), 4),
                    **{k: info.get(k) for k in ("level", "xp", "kills", "deaths", "quests_done", "copper")},
                })
                o, _ = env.reset()          # auto-reset; fresh seed stream from env
                self.obs[i] = o
                self.ep_return[i] = 0; self.ep_len[i] = 0
        return dones, rewards

    def close(self):
        for env in self.envs:
            env.close()


# ------------------------------------------------------------------ policy runner
class Runner:
    """One brain instance + one policy net; produces actions and PPO tensors."""

    def __init__(self, args, n_envs: int, obs_dim: int, n_actions: int, device="cpu"):
        self.args = args
        self.device = device
        self.brain = FlyBrain(device=device) if args.policy == "fly" else None
        if args.policy == "fly":
            torch.manual_seed(args.seed)
            self.net = FlyBrainReadout(self.brain.n_dn, n_actions).to(device)
        else:
            torch.manual_seed(args.seed)
            self.net = MLPControl(obs_dim, n_actions).to(device)
        self.opt = torch.optim.Adam(self.net.parameters(), lr=args.lr)
        self.n_actions = n_actions
        # Ability actions are gated by the game's GCD: casting again while it
        # ticks mostly queues/voids. Measured on the committed v2 checkpoint:
        # 71.6% of steps were ability casts spread over all 48 slots, i.e. the
        # policy spent most of an episode on a 1-per-GCD resource.
        self.mask_abilities = getattr(args, "mask_abilities", False)
        self.ability_idx = getattr(args, "ability_idx", None)

    def feats(self, obs: np.ndarray, silenced: bool = False) -> torch.Tensor:
        if self.brain is not None:
            f = np.stack([extract_features(o) for o in obs])
            return self.brain.step(torch.as_tensor(f, device=self.device), silenced=silenced)
        return torch.as_tensor(obs, device=self.device)

    def episode_reset(self, batch: int):
        if self.brain is not None:
            self.brain.reset(batch)

    @torch.no_grad()
    def act(self, feats: torch.Tensor, mask: torch.Tensor | None = None,
            deterministic: bool = False):
        logits, value = self.net(feats)
        if mask is not None:
            logits = logits.masked_fill(~mask, -1e9)
        dist = torch.distributions.Categorical(logits=logits)
        a = logits.argmax(-1) if deterministic else dist.sample()
        return a.cpu().numpy(), dist.log_prob(a), value, dist.entropy()


# ------------------------------------------------------------------ PPO
def ppo_update(net, opt, batch, clip=0.2, ent_coef=0.02, vf_coef=0.5, epochs=4, mb=64):
    """mask: (N, n_actions) True = allowed; must match the mask used at sampling,
    otherwise the importance ratio is computed against a different policy."""
    n = batch["feats"].shape[0]
    adv = batch["adv"]
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    stats = {}
    for _ in range(epochs):
        perm = torch.randperm(n)
        for s in range(0, n, mb):
            ix = perm[s:s + mb]
            logits, value = net(batch["feats"][ix])
            if batch.get("mask") is not None:
                logits = logits.masked_fill(~batch["mask"][ix], -1e9)
            dist = torch.distributions.Categorical(logits=logits)
            logp = dist.log_prob(batch["action"][ix])
            ratio = torch.exp(logp - batch["logp"][ix])
            pg = -torch.min(ratio * adv[ix], ratio.clamp(1 - clip, 1 + clip) * adv[ix]).mean()
            v_clip = batch["value"][ix] + (value - batch["value"][ix]).clamp(-clip, clip)
            vf = 0.5 * torch.max((value - batch["ret"][ix]) ** 2, (v_clip - batch["ret"][ix]) ** 2).mean()
            ent = dist.entropy().mean()
            loss = pg + vf_coef * vf - ent_coef * ent
            opt.zero_grad(); loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 0.5)
            opt.step()
            stats = {"pg": float(pg), "vf": float(vf), "ent": float(ent)}
    return stats


def compute_gae(rewards, values, dones, last_value, gamma=0.99, lam=0.95):
    """rewards/values/dones: (T, B); last_value: (B,)."""
    adv = torch.zeros_like(rewards)
    last = torch.zeros_like(last_value)
    T = len(rewards)
    for t in reversed(range(T)):
        nonterm = 1.0 - dones[t].float()
        next_v = last_value if t == T - 1 else values[t + 1]
        delta = rewards[t] + gamma * next_v * nonterm - values[t]
        last = delta + gamma * lam * nonterm * last
        adv[t] = last
    return adv, adv + values


def ability_mask(obs: np.ndarray, ability_idx, n_actions: int, gcd_threshold: float = 1e-3):
    """True = action allowed. src/sim/obs.ts: obs[8] = gcdRemaining / GCD, so any
    value above the threshold means abilities are on cooldown and a cast would
    only queue."""
    o = np.asarray(obs, dtype=np.float32)
    allowed = np.ones((o.shape[0], n_actions), dtype=bool)
    if ability_idx is None or not len(ability_idx):
        return torch.as_tensor(allowed)
    ticking = np.nonzero(o[:, 8] > gcd_threshold)[0]
    if len(ticking):
        allowed[np.ix_(ticking, np.asarray(ability_idx))] = False
    return torch.as_tensor(allowed)


def train(args):
    OUT.mkdir(exist_ok=True)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    rewards = json.loads(args.rewards) if args.rewards else None
    batch = EnvBatch(args.envs, args.max_steps, args.player_class, rewards=rewards)
    obs_dim = batch.envs[0].observation_space.shape[0]
    n_actions = batch.envs[0].action_space.n
    action_names = batch.envs[0].action_names
    args.ability_idx = [i for i, name in enumerate(action_names) if name.startswith("ability_")]
    runner = Runner(args, args.envs, obs_dim, n_actions)
    batch.reset([int(rng.integers(1, 900000)) for _ in range(args.envs)])
    runner.episode_reset(args.envs)

    log = []
    t0 = time.time()
    for update in range(1, args.updates + 1):
        buf = {"feats": [], "action": [], "logp": [], "value": [], "reward": [], "done": [],
               "mask": []}
        for _ in range(args.steps):
            feats = runner.feats(batch.obs)
            mask = (ability_mask(batch.obs, runner.ability_idx, n_actions)
                    if runner.mask_abilities else None)
            actions, logp, value, _ = runner.act(feats, mask=mask)
            buf["mask"].append(mask if mask is not None else torch.ones(len(batch.obs), n_actions, dtype=torch.bool))
            dones, rewards = batch.step(actions)
            buf["feats"].append(feats); buf["action"].append(torch.as_tensor(actions))
            buf["logp"].append(logp); buf["value"].append(value)
            buf["reward"].append(torch.as_tensor(rewards))
            buf["done"].append(torch.as_tensor(dones))
        stats = _finish_update(runner, buf, batch)
        ep = list(batch.finished); batch.finished.clear()
        row = {"update": update, "seconds": round(time.time() - t0, 1), **stats,
               "episodes": len(ep)}
        if ep:
            row["ep_return"] = round(float(np.mean([e["reward"] for e in ep])), 4)
            row["ep_len"] = round(float(np.mean([e["steps"] for e in ep])), 1)
            row["max_level"] = int(max(e["level"] for e in ep))
            row["total_kills"] = int(sum(e["kills"] for e in ep))
        log.append(row)
        if update % 10 == 0 or update == 1:
            print(f"update {update:4d} | {row.get('episodes', 0):3d} eps | "
                  f"ret {row.get('ep_return', float('nan')):8.3f} | len {row.get('ep_len', float('nan')):6.1f} | "
                  f"lvl {row.get('max_level', '-')} | ent {stats['ent']:.3f} | {row['seconds']:.0f}s", flush=True)

    tag = f"_{args.tag}" if args.tag else ""
    params_path = OUT / f"params_{args.policy}{tag}.pt"
    torch.save({"state": runner.net.state_dict(), "seed": args.seed, "updates": args.updates,
                "policy": args.policy, "n_actions": n_actions}, params_path)
    (OUT / f"train_log_{args.policy}{tag}.json").write_text(json.dumps(
        {"config": vars(args), "log": log}, indent=1))
    print("saved", params_path)
    batch.close()


def _finish_update(runner, buf, batch):
    """Assemble rollout tensors (per-env rewards were captured in step) and update."""
    feats = torch.stack(buf["feats"]); action = torch.stack(buf["action"])
    logp = torch.stack(buf["logp"]); value = torch.stack(buf["value"])
    reward = torch.stack(buf["reward"]); done = torch.stack(buf["done"])
    with torch.no_grad():
        last_value = runner.net(runner.feats(batch.obs))[1]
    adv, ret = compute_gae(reward, value, done, last_value)
    mask = torch.stack(buf["mask"]).reshape(-1, feats.shape[-1] and buf["mask"][0].shape[-1]) \
        if runner.mask_abilities else None
    stats = ppo_update(runner.net, runner.opt, {
        "feats": feats.reshape(-1, feats.shape[-1]), "action": action.reshape(-1),
        "logp": logp.reshape(-1), "value": value.reshape(-1),
        "adv": adv.reshape(-1), "ret": ret.reshape(-1), "mask": mask})
    return stats


# ------------------------------------------------------------------ evaluation
_ACTION_NAMES: list[str] | None = None


def evaluate(args, policy_kind: str, params: dict | None, n_episodes: int, seed0: int):
    """One env, fixed seeds. policy_kind: fly|fly-silenced|fly-untrained|mlp|random|openloop"""
    global _ACTION_NAMES
    rewards = json.loads(args.rewards) if args.rewards else None
    env = WoWClassicEnv(player_class=args.player_class, max_steps=args.max_steps, rewards=rewards)
    _ACTION_NAMES = env.action_names
    if getattr(args, "mask_abilities", False):
        args.ability_idx = [i for i, name in enumerate(env.action_names) if name.startswith("ability_")]
    n_actions = env.action_space.n
    obs_dim = env.observation_space.shape[0]
    sampled = policy_kind.endswith("-sampled")
    base = policy_kind[:-len("-sampled")] if sampled else policy_kind
    brain = FlyBrain() if base.startswith("fly") else None
    net = None
    if base.startswith("fly"):
        torch.manual_seed(args.seed)
        net = FlyBrainReadout(brain.n_dn, n_actions)
        if params is not None and base != "fly-untrained":
            net.load_state_dict(params["state"])
    elif base.startswith("mlp"):
        net = MLPControl(obs_dim, n_actions)
        if params is not None:
            net.load_state_dict(params["state"])
    net.eval() if net is not None else None
    action_names = env.action_names
    episodes = []
    for k in range(n_episodes):
        seed = seed0 + k
        obs, info = env.reset(seed=seed)
        if brain is not None:
            brain.reset(1)
        total = 0.0; steps = 0
        trace = []
        prev_events = {"kills": 0, "deaths": 0, "quests_done": 0, "level": 1}
        while True:
            if policy_kind == "random":
                a = int(env.action_space.sample())
            elif policy_kind == "openloop":
                a = 1 if steps % 2 == 0 else 9        # forward / attack
            else:
                with torch.no_grad():
                    if brain is not None:
                        f = brain.step(torch.as_tensor(extract_features(obs)[None]),
                                       silenced=(base == "fly-silenced"))
                    else:
                        f = torch.as_tensor(obs[None])
                    logits = net(f)[0]
                    if getattr(args, "mask_abilities", False) and getattr(args, "ability_idx", None):
                        m = ability_mask(np.asarray(obs)[None], args.ability_idx, n_actions)
                        logits = logits.masked_fill(~m, -1e9)
                    if sampled:
                        a = int(torch.distributions.Categorical(logits=logits).sample())
                    else:
                        a = int(logits.argmax(-1))
            obs, r, term, trunc, info = env.step(a)
            total += r; steps += 1
            # compact per-step trace: only action changes and game events
            events = {key: info.get(key) for key in ("kills", "deaths", "quests_done", "level")}
            ev_delta = {key: v for key, v in events.items() if v != prev_events.get(key)}
            if ev_delta or (trace and trace[-1][1] != a) or steps == 1:
                trace.append([steps, a, round(total, 3), ev_delta or None])
                prev_events = events
            if term or trunc:
                break
        episodes.append({"seed": seed, "steps": steps, "reward": round(total, 4),
                         "trace_len": len(trace), "trace": trace[-400:],
                         **{key: info.get(key) for key in ("level", "xp", "kills", "deaths", "quests_done")}})
        print(f"  {policy_kind:15s} seed {seed}: steps {steps:5d} reward {total:9.3f} "
              f"lvl {info.get('level')} xp {info.get('xp')} kills {info.get('kills')} "
              f"deaths {info.get('deaths')} quests {info.get('quests_done')}", flush=True)
    env.close()
    summary = {"episodes": len(episodes),
               "mean_reward": round(float(np.mean([e["reward"] for e in episodes])), 4),
               "mean_steps": round(float(np.mean([e["steps"] for e in episodes])), 1),
               "mean_level": round(float(np.mean([e["level"] for e in episodes])), 2),
               "mean_xp": round(float(np.mean([e["xp"] for e in episodes])), 1),
               "total_kills": int(sum(e["kills"] for e in episodes)),
               "total_deaths": int(sum(e["deaths"] for e in episodes)),
               "total_quests": int(sum(e["quests_done"] for e in episodes))}
    return {"condition": policy_kind, "summary": summary, "episodes": episodes}


def benchmark(args):
    OUT.mkdir(exist_ok=True)
    tag = f"_{args.tag}" if args.tag else ""
    fly_path, mlp_path = OUT / f"params_fly{tag}.pt", OUT / f"params_mlp{tag}.pt"
    fly_params = torch.load(fly_path, weights_only=False) if fly_path.exists() else None
    mlp_params = torch.load(mlp_path, weights_only=False) if mlp_path.exists() else None
    results = []
    if args.conditions:
        conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    else:
        conditions = ["fly", "fly-sampled", "fly-silenced", "fly-untrained", "random", "openloop"]
        if mlp_params is not None:
            conditions[2:2] = ["mlp", "mlp-sampled"]
    for cond in conditions:
        base = cond[:-len("-sampled")] if cond.endswith("-sampled") else cond
        params = {"fly": fly_params, "fly-silenced": fly_params, "mlp": mlp_params}.get(base)
        if cond.startswith("fly") and fly_params is None:
            print(f"skip {cond}: no params_fly.pt"); continue
        print(f"[{cond}]")
        results.append(evaluate(args, cond, params, args.eval_episodes, args.eval_seed))
    bench = {"environment": "world-of-claudecraft (levy-street, headless env_server)",
             "env_version": {"obs": 607, "actions": 61},
             "action_names": _ACTION_NAMES,
             "circuit": json.loads((Path(__file__).parent / "data" / "manifest.json").read_text()),
             "eval_config": {"episodes": args.eval_episodes, "seed0": args.eval_seed,
                             "max_steps": args.max_steps, "player_class": args.player_class,
                             "rewards": json.loads(args.rewards) if args.rewards else "server defaults",
                             "tag": args.tag or None},
             "results": results,
             "note": ("Our own exported rollouts are the evidence; upstream project results are not. "
                      "Circuit is a bounded DN-centric subset (circuit subset), frozen; only the "
                      "artificial readout is trained.")}
    out_path = OUT / f"benchmark{tag}.json"
    if args.conditions and out_path.exists():     # merge into the existing benchmark
        prev = json.loads(out_path.read_text())
        by_cond = {r["condition"]: r for r in prev.get("results", [])}
        by_cond.update({r["condition"]: r for r in results})
        bench["results"] = [by_cond[c] for c in
                            (list(prev.get("order", [])) or list(by_cond)) if c in by_cond]
        have = {r["condition"] for r in bench["results"]}
        for r in results:
            if r["condition"] not in have:
                bench["results"].append(r)
        bench["order"] = [r["condition"] for r in bench["results"]]
    out_path.write_text(json.dumps(bench, indent=1))
    print("wrote", out_path)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--policy", choices=["fly", "mlp"], default="fly")
    p.add_argument("--updates", type=int, default=400)
    p.add_argument("--steps", type=int, default=96, help="env steps per env per update")
    p.add_argument("--envs", type=int, default=2)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--seed", type=int, default=20260914)
    p.add_argument("--max-steps", type=int, default=1200, dest="max_steps")
    p.add_argument("--player-class", default="warrior", dest="player_class")
    p.add_argument("--eval-only", action="store_true")
    p.add_argument("--no-bench", action="store_true", dest="no_bench", help="train without the auto benchmark")
    p.add_argument("--eval-episodes", type=int, default=5, dest="eval_episodes")
    p.add_argument("--rewards", default=None, help='JSON dict overriding env rewards')
    p.add_argument("--tag", default="", help="suffix for params/log/benchmark filenames")
    p.add_argument("--conditions", default=None, help="comma-separated subset of conditions to evaluate (merged into existing benchmark)")
    p.add_argument("--eval-seed", type=int, default=900001, dest="eval_seed")
    p.add_argument("--mask-abilities", action="store_true", dest="mask_abilities",
                   help="block ability actions while the GCD ticks (kills the 71.6%-of-steps cast spam); "
                        "train and evaluate with the same flag")
    args = p.parse_args()
    if args.eval_only:
        benchmark(args)
    else:
        train(args)
        if not args.no_bench:
            benchmark(args)
