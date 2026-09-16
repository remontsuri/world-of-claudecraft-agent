#!/usr/bin/env python3
"""progress_eval.py — прогресс-метрики мухи в реальном офлайн-симе WoC.

Отвечает на вопрос «играет ли муха», а не «какой у неё reward»: reward можно
набрать стоя на месте (timePenalty отрицательный, но questProgress капает), а
прогресс — нет.

Запуск (офлайн-сим — тот же src/sim, что и в браузерном Play Offline):

    WOC_PYTHON_PATH=/path/to/world-of-claudecraft/python \
    python3 progress_eval.py --checkpoint outputs/params_fly_v2.pt --episodes 3

Печатает по эпизоду: уровень, xp, киллы, смерти, квесты, пройденный путь,
разнообразие действий — и сводку против порогов приёмки.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, os.environ.get("WOC_PYTHON_PATH", "/home/user/woc-game/python"))
sys.path.insert(0, str(Path(__file__).parent))

from wow_env import WoWClassicEnv  # noqa: E402
from fly_brain import FlyBrain, extract_features, FEATURE_VERSION  # noqa: E402
from quest_oracle import load_table, oracle_vector  # noqa: E402
from agent import FlyBrainReadout, MLPControl  # noqa: E402

# xp-таблица игры (src/sim/types.ts, XP_TABLE): xp внутри уровня -> суммарно
XP_TABLE = [400, 900, 1400, 2100, 2800, 3600, 4500, 5400, 6500, 7600,
            8800, 10100, 11400, 12900, 14400, 16000, 17700, 19400, 21300, 23200]
MAX_LEVEL = 20
XP_TO_LEVEL = {lvl: sum(XP_TABLE[: lvl - 1]) for lvl in range(2, MAX_LEVEL + 1)}

# Пороги приёмки: что считаем «полноценно играет» на данном горизонте.
# M1 — уровень 2 (первый реальный прогресс), M2 — боевой цикл,
# M3 — квестовый цикл, M4 — перемещение по миру (путь, а не топтание).
ACCEPTANCE = {
    "M1_level2": {"level": 2},
    "M2_combat": {"kills": 10},
    "M3_quests": {"quests_done": 5},
    "M4_travel": {"travel_norm": 2.0},   # нормированные единицы obs (≈ 2 x WORLD_MAX_X)
}


def ability_mask(obs: np.ndarray, ability_idx, n_actions: int, gcd_threshold: float = 1e-3):
    """True = action allowed. obs[8] = gcdRemaining / GCD (src/sim/obs.ts), so a value
    above the threshold means abilities are on cooldown and a cast would only queue.
    Same rule as train.py: a policy trained with the mask must be measured with it."""
    o = np.asarray(obs, dtype=np.float32)
    allowed = np.ones((o.shape[0], n_actions), dtype=bool)
    if ability_idx is None or not len(ability_idx):
        return torch.as_tensor(allowed)
    ticking = np.nonzero(o[:, 8] > gcd_threshold)[0]
    if len(ticking):
        allowed[np.ix_(ticking, np.asarray(ability_idx))] = False
    return torch.as_tensor(allowed)


def run_episode(env, brain, net, policy: str, seed: int, max_steps: int, ability_idx=None,
                oracle_tbl=None):
    obs, info = env.reset(seed=seed)
    if brain is not None:
        brain.reset(1)
    total, steps = 0.0, 0
    acts = Counter()
    px = pz = None
    travel = 0.0
    first_quest_at = None
    prev_quests = 0
    while True:
        if policy == "random":
            a = int(env.action_space.sample())
        elif policy == "openloop":
            a = 1 if steps % 2 == 0 else 9
        else:
            with torch.no_grad():
                if brain is not None:
                    f = brain.step(torch.as_tensor(extract_features(obs)[None]),
                                   silenced=(policy == "fly-silenced"))
                    if oracle_tbl is not None:
                        f = torch.cat([f, torch.as_tensor(
                            oracle_vector(obs, table=oracle_tbl)[None])], dim=1)
                else:
                    f = torch.as_tensor(obs[None])
                logits = net(f)[0]
                if ability_idx:
                    m = ability_mask(np.asarray(obs)[None], ability_idx, logits.shape[-1])
                    logits = logits.masked_fill(~m[0], -1e9)
                a = (int(torch.distributions.Categorical(logits=logits).sample())
                     if policy.endswith("-sampled") else int(logits.argmax(-1)))
        obs, r, term, trunc, info = env.step(a)
        total += r
        steps += 1
        acts[env.action_names[a]] += 1
        # путь по глобальной позиции из obs (src/sim/obs.ts: x -> obs[4], z -> obs[5])
        x, z = float(obs[4]), float(obs[5])
        if px is not None:
            travel += float(np.hypot(x - px, z - pz))
        px, pz = x, z
        qd = int(info.get("quests_done", 0) or 0)
        if qd > prev_quests and first_quest_at is None:
            first_quest_at = steps
        prev_quests = qd
        if term or trunc:
            break
    level = int(info.get("level", 1) or 1)
    xp = int(info.get("xp", 0) or 0)
    out = {
        "seed": seed, "steps": steps, "reward": round(total, 3),
        "level": level, "xp": xp,
        "xp_to_next": XP_TO_LEVEL.get(level + 1, 0) - sum(XP_TABLE[: level - 1]) - xp if level < MAX_LEVEL else 0,
        "kills": int(info.get("kills", 0) or 0),
        "deaths": int(info.get("deaths", 0) or 0),
        "quests_done": int(info.get("quests_done", 0) or 0),
        "first_quest_at_step": first_quest_at,
        "travel_norm": round(travel, 3),
        "actions_used": len(acts),
    }
    top = acts.most_common(3)
    out["top_actions"] = [f"{k} {100*v/steps:.0f}%" for k, v in top]
    out["_acts"] = dict(acts)
    return out


def build(policy: str, checkpoint: Path | None, seed: int, obs_dim: int, n_actions: int,
          oracle_extra: int = 0):
    base = policy[:-len("-sampled")] if policy.endswith("-sampled") else policy
    brain = FlyBrain() if base.startswith("fly") else None
    net = None
    if base.startswith("fly"):
        torch.manual_seed(seed)
        net = FlyBrainReadout(brain.n_dn + oracle_extra, n_actions)
        if checkpoint is not None and base != "fly-untrained":
            net.load_state_dict(torch.load(checkpoint, weights_only=False)["state"])
        net.eval()
    elif base.startswith("mlp"):
        net = MLPControl(obs_dim, n_actions)
        if checkpoint is not None:
            net.load_state_dict(torch.load(checkpoint, weights_only=False)["state"])
        net.eval()
    return brain, net


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="fly-sampled",
                    choices=["fly", "fly-sampled", "fly-silenced", "fly-untrained", "mlp", "mlp-sampled", "random", "openloop"])
    ap.add_argument("--checkpoint", type=Path, default=Path(__file__).parent / "outputs" / "params_fly_v2.pt")
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=8000, dest="max_steps",
                    help="полная длина эпизода сервера (DEFAULT_CONFIG.maxSteps = 8000)")
    ap.add_argument("--seed0", type=int, default=900001)
    ap.add_argument("--torch-seed", type=int, default=20260914, dest="torch_seed",
                    help="сид сэмплинга действий; должен совпадать с train.py --seed, иначе эпизод другой")
    ap.add_argument("--rewards", default='{"xp": 0.02, "kill": 1.0, "timePenalty": 0.001, "questProgress": 1.0, "questDone": 10, "levelUp": 5}')
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--oracle-obs", action="store_true", dest="oracle_obs",
                    help="policy was trained with the quest-oracle side channel (+5 inputs)")
    ap.add_argument("--mask-abilities", action="store_true", dest="mask_abilities",
                    help="mask ability_* actions while the GCD ticks (must match training)")
    args = ap.parse_args()

    rewards = json.loads(args.rewards) if args.rewards else None
    env = WoWClassicEnv(player_class="warrior", max_steps=args.max_steps, rewards=rewards)
    ckpt = args.checkpoint if args.checkpoint and Path(args.checkpoint).exists() else None
    from obs_layout import configure as _configure_layout
    _layout = _configure_layout(obs_size=env.observation_space.shape[0], n_actions=env.action_space.n)
    print(f"[obs] {_layout.describe()}", flush=True)
    oracle_tbl = load_table() if (args.oracle_obs and args.policy == "fly") else None
    brain, net = build(args.policy, ckpt, args.torch_seed, env.observation_space.shape[0],
                       env.action_space.n, oracle_extra=5 if oracle_tbl is not None else 0)

    print(f"policy={args.policy} encoder={FEATURE_VERSION} "
          f"checkpoint={ckpt if ckpt else '(none)'} max_steps={args.max_steps}"
          f"{' mask=GCD' if args.mask_abilities else ''}"
          f"{' oracle=side-channel' if oracle_tbl is not None else ''}")
    print(f"{'seed':>8} {'steps':>6} {'reward':>9} {'lvl':>4} {'xp':>6} {'to_next':>8} "
          f"{'kills':>6} {'deaths':>7} {'quests':>7} {'1st_q':>6} {'travel':>8} {'acts':>5}")
    ability_idx = ([i for i, name in enumerate(env.action_names) if name.startswith("ability_")]
                   if args.mask_abilities else None)
    rows = []
    for k in range(args.episodes):
        r = run_episode(env, brain, net, args.policy, args.seed0 + k, args.max_steps,
                        ability_idx=ability_idx, oracle_tbl=oracle_tbl)
        rows.append(r)
        print(f"{r['seed']:>8} {r['steps']:>6} {r['reward']:>9} {r['level']:>4} {r['xp']:>6} "
              f"{r['xp_to_next']:>8} {r['kills']:>6} {r['deaths']:>7} {r['quests_done']:>7} "
              f"{str(r['first_quest_at_step'] or '-'):>6} {r['travel_norm']:>8} {r['actions_used']:>5}")
    env.close()

    print("\nдействия (все эпизоды):")
    total_acts = Counter()
    for r in rows:
        total_acts.update(r.pop("_acts"))
    n = sum(total_acts.values())
    for k, v in total_acts.most_common(8):
        print(f"  {k:14s} {100*v/n:5.1f}%")

    agg = {key: float(np.mean([r[key] for r in rows]))
           for key in ("level", "xp", "kills", "deaths", "quests_done", "travel_norm", "reward")}
    print("\nсреднее:", {k: round(v, 3) for k, v in agg.items()})

    print("\nприёмка (среднее по эпизодам):")
    verdict = {}
    for name, need in ACCEPTANCE.items():
        ok = all(agg[k] >= v for k, v in need.items())
        verdict[name] = ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name:12s} нужно {need}")
    if verdict.get("M1_level2") and verdict.get("M2_combat") and verdict.get("M3_quests"):
        print("  -> прогресс есть: боевой и квестовый циклы работают")
    else:
        print("  -> прогресса уровня/боя/квестов нет: политика выживает, но не играет")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"policy": args.policy, "encoder": FEATURE_VERSION,
                                        "max_steps": args.max_steps, "aggregate": agg,
                                        "acceptance": verdict, "episodes": rows}, indent=1))
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
