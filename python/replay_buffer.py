"""Replay Buffer — store transitions, prioritize RARE events.

Per user 2026-08-20: do NOT update Q from only the last transition. 1000
explore steps would drown one useful turn_in. Instead:

  - store (state, action, reward, next_state, done, goal, skill, event)
  - rare events get a HIGHER sampling probability:
      QUEST_ACCEPT_SUCCESS, OBJECTIVE_PROGRESS, QUEST_TURNIN_SUCCESS,
      DEATH, RESPAWN_SUCCESS, VENDOR_SUCCESS
  - ordinary steps (explore/farm/loot) are kept but sampled less often.
  - a bounded ring (cap 10k-50k) so memory does not grow unbounded.

The Q-learning update (memory.py) will draw BATCHES from here instead of the
single most-recent transition, so rare-but-valuable lessons are actually seen.
"""

import json
import os
import random
import tempfile
import traceback
from collections import deque
from typing import Dict, List, Optional


# Rare events that must not be drowned out by common steps.
RARE_EVENTS = {
    "QUEST_ACCEPT_SUCCESS",
    "OBJECTIVE_PROGRESS",
    "QUEST_TURNIN_SUCCESS",
    "DEATH",
    "RESPAWN_SUCCESS",
    "VENDOR_SUCCESS",
    "QUEST_FAIL",
}

# Sampling weight for a stored transition, by event class.
EVENT_SAMPLE_WEIGHT = {
    "QUEST_ACCEPT_SUCCESS": 8.0,
    "OBJECTIVE_PROGRESS": 6.0,
    "QUEST_TURNIN_SUCCESS": 12.0,
    "DEATH": 5.0,
    "RESPAWN_SUCCESS": 3.0,
    "VENDOR_SUCCESS": 4.0,
    "QUEST_FAIL": 5.0,
}
COMMON_WEIGHT = 1.0  # explore/farm/loot/heal with no notable event


class ReplayBuffer:
    def __init__(self, cap: int = 20000, path: Optional[str] = None,
                 rare_boost: float = 4.0):
        self.cap = cap
        self.rare_boost = rare_boost  # extra multiplier for rare events
        self.path = path or os.path.join(os.path.dirname(__file__), "replay_buffer.json")
        self.buffer: deque = deque(maxlen=cap)
        self._load()

    # ---- persistence ----
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("buffer") or []
            # keep only up to cap
            for it in items[-self.cap:]:
                self.buffer.append(it)
        except Exception:
            return

    def save(self):
        try:
            d = os.path.dirname(os.path.abspath(self.path)) or "."
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".rb_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                # Persist a bounded tail (full buffer can be large); the buffer
                # itself is the source of truth at runtime, this is a warm restart.
                json.dump({"buffer": list(self.buffer)[-5000:]}, f,
                          ensure_ascii=False, indent=0)
            os.replace(tmp, self.path)
        except Exception:
            traceback.print_exc()

    # ---- ingest ----
    def add(self, transition: Dict):
        """transition = {
            state, action, reward, next_state, done,
            goal, skill, event  (event optional; rare ones boost sampling)
        }"""
        ev = transition.get("event")
        # tag the transition with its sampling weight
        if ev in EVENT_SAMPLE_WEIGHT:
            w = EVENT_SAMPLE_WEIGHT[ev] * self.rare_boost
        else:
            w = COMMON_WEIGHT
        item = dict(transition)
        item["_w"] = w
        self.buffer.append(item)

    # ---- sample ----
    def sample(self, n: int = 32) -> List[Dict]:
        """Sample n transitions with probability proportional to _w.

        Falls back to uniform if the buffer is too small or weights degenerate.
        """
        if len(self.buffer) == 0:
            return []
        if len(self.buffer) <= n:
            return list(self.buffer)
        weights = [max(it.get("_w", COMMON_WEIGHT), 0.01) for it in self.buffer]
        total = sum(weights)
        if total <= 0:
            return random.sample(list(self.buffer), n)
        # weighted sampling without replacement (reservoir-style)
        chosen = []
        pool = list(range(len(self.buffer)))
        import bisect
        cum = []
        acc = 0.0
        for w in weights:
            acc += w
            cum.append(acc)
        chosen_idx = set()
        attempts = 0
        while len(chosen_idx) < n and attempts < n * 10:
            attempts += 1
            r = random.random() * total
            idx = bisect.bisect_left(cum, r)
            idx = min(idx, len(self.buffer) - 1)
            if idx not in chosen_idx:
                chosen_idx.add(idx)
                chosen.append(self.buffer[idx])
        return chosen

    def __len__(self):
        return len(self.buffer)
