"""Collect Oracle navigation traces (NO training, NO Sim/reward/obs changes).

Imports the EXISTING validated Oracle (audit_common.oracle_action, 10/10 kills
on seeds 42..51) — does NOT rewrite Oracle logic. For each step records the raw
obs, the Oracle action, and derived navigation features from nav_features.py.

Saved as JSONL (one Transition per line) so BC-raw and BC-feature can both read
the same source without re-collecting.

Run:
  therock-test/Scripts/python.exe oracle_nav_dataset.py
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
_WOC = Path(r"D:/world-of-claudecraft/python")
if str(_WOC) not in sys.path:
    sys.path.insert(0, str(_WOC))
# audit_common (the validated Oracle) lives in the woc-llm workdir, not in the
# game repo — add it to the path so we reuse the exact 10/10 Oracle.
_WLLM = Path(r"D:/woc-llm")
if str(_WLLM) not in sys.path:
    sys.path.insert(0, str(_WLLM))

import numpy as np

import audit_common as ac
import curriculum_env as ce
import nav_features as nf

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "nav_data"
OUT_DIR.mkdir(exist_ok=True)
OUT = OUT_DIR / "oracle_nav_traces.jsonl"

# ability_slots comes from the verified obs layout (48), not hardcoded blindly.
ABILITY_SLOTS = (ac.TGT - 16) // 2  # = 48
SEEDS = list(range(42, 62))      # 20 seeds
EPISODES_PER_SEED = 10
MAX_STEPS = 400


@dataclass
class Transition:
    obs: list
    action: int
    phase: str
    mob_visible: bool
    mob_dist: float
    mob_sin: float
    mob_cos: float
    turn_dir: int
    turn_strength: float
    forward_ok: bool
    target_has: bool
    target_dist: float
    in_combat_range: bool


def main():
    rows = []
    for seed in SEEDS:
        for ep in range(EPISODES_PER_SEED):
            env = ce.CurriculumEnv(stage=3, player_class="warrior",
                                   max_steps=MAX_STEPS, frame_skip=5)
            obs, info = env.reset(seed=seed)
            aid = ac.make_aid(env.action_names)
            prev = {}
            tracker = nf.CombatRangeTracker()
            for i in range(1, MAX_STEPS + 1):
                act = int(ac.oracle_action(obs, aid, prev))
                nxt, r, term, trunc, info = env.step(act)

                target, mob = nf.decode_nav_obs(obs, ABILITY_SLOTS)
                icr = tracker.update(bool(target["has"]), target["dist"])
                if mob is not None:
                    nf_obj = nf.make_nav_features(
                        mob_dist=mob["dist"], mob_sin=mob["sin"],
                        mob_cos=mob["cos"], target_has=bool(target["has"]),
                        target_dist=target["dist"], target_sin=target["sin"],
                        target_cos=target["cos"], in_combat_range=icr)
                else:
                    nf_obj = nf.make_nav_features(
                        mob_dist=nf.MOB_SAT * nf.DIST_SCALE, mob_sin=0.0, mob_cos=0.0,
                        target_has=bool(target["has"]), target_dist=target["dist"],
                        target_sin=target["sin"], target_cos=target["cos"],
                        in_combat_range=icr)
                rows.append(Transition(
                    obs=list(map(float, obs)),
                    action=act,
                    phase=nf_obj.phase,
                    mob_visible=nf_obj.mob_visible,
                    mob_dist=nf_obj.mob_dist,
                    mob_sin=nf_obj.mob_sin,
                    mob_cos=nf_obj.mob_cos,
                    turn_dir=nf_obj.turn_dir,
                    turn_strength=nf_obj.turn_strength,
                    forward_ok=nf_obj.forward_ok,
                    target_has=nf_obj.target_has,
                    target_dist=nf_obj.target_dist,
                    in_combat_range=nf_obj.in_combat_range,
                ))
                obs = nxt
                if term or trunc:
                    break
            env.close()

    with open(OUT, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(asdict(row)) + "\n")
    print(f"SAVED {OUT}  transitions={len(rows)}  ability_slots={ABILITY_SLOTS}")


if __name__ == "__main__":
    main()
