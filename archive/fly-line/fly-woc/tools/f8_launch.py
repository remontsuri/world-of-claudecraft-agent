"""F8 launcher: run each (condition, seed) in a subprocess to avoid OOM."""
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent        # .../fly-woc/tools/
FLY = HERE.parent                             # .../fly-woc/
ROOT = FLY.parent                             # .../world-of-claudecraft/
PY = "D:/unsloth-studio/unsloth_studio/Scripts/python.exe"
SEEDS = [900001, 900101, 900201]
CONDITIONS = [
    ("fly-sampled",    None,                              "our"),
    ("fly",            None,                              "fly-argmax"),
    ("fly-sampled",    str(ROOT / "data/circuit_rewired.json"), "rewired"),
    ("fly-sampled",    str(ROOT / "data/circuit_er.json"),      "er"),
    ("fly-silenced",   None,                              "silenced"),
    ("fly-untrained",  None,                              "untrained"),
]
MAX_STEPS = 1200
EPISODES = 5
import os
env = dict(os.environ)
env["PYTHONPATH"] = f"{ROOT};{FLY}"
env["WOC_PYTHON_PATH"] = "D:/woc-game/python"

results = {}
for policy, circuit, label in CONDITIONS:
    for seed0 in SEEDS:
        print(f"\n=== {label} seed={seed0} ===", flush=True)
        cmd = [PY, "-u", str(HERE / "f8_one.py"),
               "--policy", policy, "--seed0", str(seed0),
               "--episodes", str(EPISODES), "--max-steps", str(MAX_STEPS),
               "--device", "cuda", "--label", label]
        if circuit:
            cmd += ["--circuit", circuit]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        if proc.returncode != 0:
            print(f"  FAILED (code={proc.returncode})")
            err = proc.stderr.decode("utf-8", errors="replace")[-400:]
            print(f"  STDERR: {err}", flush=True)
            continue
        print(proc.stdout.decode("utf-8", errors="replace")[-500:], flush=True)
        out_path = FLY / "outputs" / f"one_{label}_s{seed0}.json"
        if out_path.exists():
            one = json.loads(out_path.read_text())
            results[f"{label}_s{seed0}"] = {"label": label, "seed0": seed0, **one}

OUT = FLY / "outputs" / "benchmark_v3.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"conditions": results,
                           "meta": {"seeds": SEEDS, "episodes": EPISODES,
                                    "max_steps": MAX_STEPS}}, indent=1))
print(f"\nWROTE {OUT}")
