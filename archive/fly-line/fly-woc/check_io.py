"""I/O sanity check: does the game observation actually drive the circuit?

fly-craftax M2/M3 lesson: their retina stayed silent until a lamina bias was
added, and an agent can score with zero visual contribution. Check BEFORE
training that (a) DN activity is nonzero, (b) it varies across real obs,
(c) blacked-out obs changes it, (d) silencing zeroes it.
"""
import os
import sys
import numpy as np
import torch

sys.path.insert(0, os.environ.get("WOC_PYTHON_PATH", "/home/user/repos/woc-game/python"))
from wow_env import WoWClassicEnv
from fly_brain import FlyBrain, extract_features

env = WoWClassicEnv(player_class="warrior", max_steps=60)
brain = FlyBrain()
print(brain.describe(), flush=True)
obs, _ = env.reset(seed=7)
brain.reset(1)

rows = {"full": [], "black": [], "silenced": []}
for i in range(60):
    f = torch.as_tensor(extract_features(obs)[None])
    h_before = brain.state_copy()
    full_out = brain.step(f)                          # the live branch: state advances
    h_after = brain.state_copy()
    rows["full"].append(full_out.numpy()[0])
    brain.restore_state(h_before)
    rows["black"].append(brain.step(torch.zeros(1, 13, device=brain.device)).cpu().numpy()[0])
    brain.restore_state(h_before)
    rows["silenced"].append(brain.step(f, silenced=True).numpy()[0])
    brain.h = h_after                                 # restore the live branch
    a = env.action_space.sample()
    obs, *_ = env.step(a)

full = np.stack(rows["full"]); black = np.stack(rows["black"]); sil = np.stack(rows["silenced"])
active = (full != 0).mean()
print(f"DN cells: {full.shape[1]}")
print(f"full      : mean|act| {np.abs(full).mean():.4f}  active fraction {active:.3f}  "
      f"step-to-step delta {np.abs(np.diff(full, axis=0)).mean():.5f}")
print(f"black     : mean|act| {np.abs(black).mean():.4f}  active fraction {(black != 0).mean():.3f}")
print(f"silenced  : mean|act| {np.abs(sil).mean():.4f}  (must be 0)")
delta_full_black = np.abs(full - black).mean()
print(f"full-vs-black mean|delta|: {delta_full_black:.5f}  (must be > 0: obs drives the circuit)")
feat = np.stack([extract_features(env.reset(seed=100 + k)[0]) for k in range(5)])
print("feature ranges across 5 resets:")
names = ["hp", "resource", "in_combat", "gcd_ready", "target_exists", "target_dist",
         "target_hp", "target_sin", "target_cos", "nearest_mob_dist", "mob_pressure",
         "ability_ready", "quest_progress"]
for n, col in zip(names, feat.T):
    print(f"  {n:18s} min {col.min():.3f} max {col.max():.3f}")
env.close()
assert active > 0.01, "circuit is dead: no DN activity"
assert delta_full_black > 1e-4, "obs has no effect on DN activity"
assert np.abs(sil).max() == 0.0, "silencing failed"
print("OK: circuit is driven by obs, silencing works.")
