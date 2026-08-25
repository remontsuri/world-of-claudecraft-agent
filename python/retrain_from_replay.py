"""Offline consolidation of the live agent's replay into a clean Q-table.

This never invents game outcomes. It replays only transitions already observed by
play_autonomous.py. A candidate set is taken from the stored transition when
available; otherwise the current canonical policy is used only as a compatibility
fallback.
"""
import argparse
import json
import os
import random
import tempfile
from collections import defaultdict

from memory import ExperienceStore, _bucket
from hierarchical_env import SKILLS
from replay_buffer import ReplayBuffer
from policy import GoalManager


def load_replay(path, cap=20000):
    rb = ReplayBuffer(cap=cap, path=path)
    return list(rb.buffer)


def clean_transitions(items):
    out = []
    for it in items:
        state = it.get("state")
        next_state = it.get("next_state")
        action = it.get("action")
        if not isinstance(state, dict) or not isinstance(next_state, dict) or action not in SKILLS:
            continue
        # Do not learn from an infrastructure failure disguised as a zero-reward
        # terminal transition.
        if it.get("done") and it.get("event") is None and it.get("reward", 0) == 0:
            continue
        out.append(it)
    return out


def main():
    parser = argparse.ArgumentParser()
    base = os.path.dirname(__file__)
    parser.add_argument("--replay", default=os.path.join(base, "replay_buffer.json"))
    parser.add_argument("--memory", default=os.path.join(base, "experience_autonomous.json"))
    parser.add_argument("--out", default=os.path.join(base, "experience_retrained.json"))
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--seed", type=int, default=4242)
    args = parser.parse_args()
    random.seed(args.seed)

    items = clean_transitions(load_replay(args.replay))
    if not items:
        raise SystemExit("No valid replay transitions; run live self-play first.")

    # Build a fresh table. The checked-in experience_autonomous.json contains old
    # bucket schemas (for example old junk/strong-mob semantics) and must not be
    # silently mixed into the new learner. The live replay contains raw WorldState.
    mem = ExperienceStore(path=args.memory)
    mem.weights = defaultdict(float)
    mem.counts = defaultdict(int)
    mem.experiences = []
    mem.lr = 0.12
    mem.gamma = 0.92

    # Canonical action universe: exactly the live high-level skill list.
    mem.ACTIONS = list(SKILLS)
    gm = GoalManager(mem, temperature=1.0)
    rng = random.Random(args.seed)

    for _ in range(max(1, args.epochs)):
        batch = list(items) if len(items) <= args.batch else rng.sample(items, args.batch)
        for item in batch:
            state = item["state"]
            next_state = item["next_state"]
            action = item["action"]
            candidates = item.get("next_candidates")
            if not candidates:
                try:
                    candidates = gm._candidates(
                        next_state, gm._world_state(next_state), goal=item.get("goal")
                    )
                except Exception:
                    candidates = None
            next_bucket = _bucket(next_state)
            bootstrap = max(
                (mem.value(next_bucket, candidate)
                 for candidate in (candidates or mem.ACTIONS)),
                default=0.0,
            )
            key = (_bucket(state), action)
            old = mem.weights[key]
            reward = float(item.get("reward", 0.0))
            target = reward + mem.gamma * bootstrap
            mem.counts[key] += 1
            mem.weights[key] = old + mem.lr * (target - old)
            mem.experiences.append((
                _bucket(state), action, round(reward, 4), next_bucket,
                str(item.get("event") or "OK"),
            ))

    data = {
        "schema_version": 2,
        "actions": list(SKILLS),
        "weights": [[list(key), value] for key, value in mem.weights.items()],
        "counts": [[list(key), value] for key, value in mem.counts.items()],
        "experiences": [list(item) for item in mem.experiences[-5000:]],
        "source": {
            "replay": args.replay,
            "transitions": len(items),
            "epochs": args.epochs,
        },
    }
    directory = os.path.dirname(os.path.abspath(args.out)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".retrain_", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, args.out)
    print(json.dumps({
        "transitions": len(items),
        "epochs": args.epochs,
        "states": len(mem.weights),
        "out": args.out,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
