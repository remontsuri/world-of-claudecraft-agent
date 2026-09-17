"""F8 one: run one (condition, seed) combo and write result to a temp file."""
import argparse
from pathlib import Path
import json, os, sys

HERE = Path(__file__).resolve().parent        # .../fly-woc/tools/
FLY = HERE.parent                             # .../fly-woc/
ROOT = FLY.parent                             # .../world-of-claudecraft/
sys.path.insert(0, str(FLY))

from progress_eval import build, run_episode, WoWClassicEnv
from device_utils import resolve_device
from obs_layout import configure as _configure_layout

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--policy", default="fly-sampled")
    p.add_argument("--circuit", default=None)
    p.add_argument("--seed0", type=int, default=900001)
    p.add_argument("--episodes", type=int, default=5)
    p.add_argument("--max-steps", type=int, default=1200)
    p.add_argument("--device", default="cuda")
    p.add_argument("--label", default=None)
    args = p.parse_args()
    label = args.label or (
        args.policy.replace("-sampled", "") if "-sampled" in args.policy else args.policy)
    dev = resolve_device(args.device)
    env = WoWClassicEnv(player_class="warrior", max_steps=8000)
    _configure_layout(obs_size=env.observation_space.shape[0],
                      n_actions=env.action_space.n)
    ckpt = str(FLY / "outputs" / "params_fly_v2.pt")
    brain, net = build(args.policy, ckpt, 20260914,
                       env.observation_space.shape[0], env.action_space.n,
                       oracle_extra=0, circuit=args.circuit, device=dev)
    rows = []
    for k in range(args.episodes):
        r = run_episode(env, brain, net, args.policy, args.seed0 + k, args.max_steps)
        rows.append(r)
        print(f"  seed={args.seed0+k} rew={r['reward']:.3f} q={r['quests_done']} k={r['kills']} d={r['deaths']}",
              flush=True)
    env.close()

    import numpy as np
    agg = {kk: float(np.mean([r[kk] for r in rows]))
           for kk in ("level", "xp", "kills", "deaths", "quests_done", "travel_norm", "reward")}
    out = {"aggregate": agg, "episodes": rows}
    out_path = FLY / "outputs" / f"one_{label}_s{args.seed0}.json"
    out_path.write_text(json.dumps(out))
    print(f"wrote {out_path}")

if __name__ == "__main__":
    main()
