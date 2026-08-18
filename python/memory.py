"""Experience / Memory store — the learning loop's long-term memory.

Per user 2026-08-16 directive: the agent must LEARN from outcomes, not follow a
scripted if/else. This store records (state, decision, outcome, reward) and
adjusts the policy's action weights so that bad choices in a given state become
less likely next time. Death/penalty at low HP teaches "farm while low is bad"
WITHOUT a hard-coded `if HP<30: heal` rule — the agent discovers it.

Design:
- State is bucketed into coarse features (discretized) so experiences generalize.
- Each (state_bucket, action) has a weight = expected value estimate.
- After each step we get a reward (from verifier/outcome). We do a tiny
  tabular TD-ish update: weight += lr * (reward - weight). Positive rewards raise
  the weight, negative (death=-5) lower it.
- Policy samples actions proportional to weight (softmax over the candidate set),
  so it CAN still explore (and occasionally repeat a mistake — that's fine, it's
  how the value estimate stays honest).
"""

import json
import math
import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


# ---- state discretization ----------------------------------------------------
def _bucket(state: dict) -> str:
    """Coarse, comparable state key. Intentionally LOSSY so experiences transfer.

    state keys we care about (from WorldState):
      hp_frac      (0..1)
      quest_status (NONE / ACTIVE / READY_TO_TURN_IN / DONE)
      has_mob      (bool)   — hostile mob in nearby
      has_corpse   (bool)   — lootable corpse in nearby
      has_junk     (bool)   — junk-quality item in inventory
      danger       (bool)   — player in combat / low hp
      far          (bool)   — distance_to_giver > 80 (OBSERVED, not a rule)
      combat       (bool)   — in_combat (OBSERVED, not a rule)
    """
    hp = state.get("hp_frac", 1.0)
    hp_band = "crit" if hp < 0.25 else "low" if hp < 0.5 else "ok" if hp < 0.8 else "full"
    qs = state.get("quest_status", "NONE")
    dist = state.get("distance_to_giver", 0.0)
    far = 1 if (dist is not None and dist > 80) else 0
    combat = 1 if state.get("in_combat") else 0
    return "|".join([
        f"hp={hp_band}",
        f"qs={qs}",
        f"mob={1 if state.get('has_mob') else 0}",
        f"corpse={1 if state.get('has_corpse') else 0}",
        f"junk={1 if state.get('has_junk') else 0}",
        f"danger={1 if state.get('danger') else 0}",
        f"far={far}",
        f"combat={combat}",
    ])


class ExperienceStore:
    """Tabular value memory over (state_bucket, action)."""

    # Full action set used for the TD bootstrap (max_a' Q(s',a')). Must cover every
    # action the policy can ever emit, including the always-available `explore`.
    ACTIONS = ["farm", "loot", "accept_quest", "turn_in_quest", "return_to_giver",
               "heal", "sell_junk", "gather", "quest", "explore"]

    def __init__(self, lr: float = 0.2, decay: float = 0.999, gamma: float = 0.9, path: Optional[str] = None):
        # (bucket, action) -> float value estimate
        self.weights: Dict[Tuple[str, str], float] = defaultdict(float)
        # (bucket, action) -> count (for confidence / exploration bonus)
        self.counts: Dict[Tuple[str, str], int] = defaultdict(int)
        # experience log: (bucket, action, reward, next_bucket, outcome_kind)
        # This is the REAL memory the user wants: not "farm is bad" but
        # "in a similar state I did farm -> X happened -> -0.48 -> P(farm) dropped".
        self.experiences: List[Tuple[str, str, float, str, str]] = []
        self.lr = lr
        self.decay = decay
        self.gamma = gamma
        self.path = path or os.path.join(os.path.dirname(__file__), "experience.json")
        self._load()

    # ---- persistence ----
    def _load(self):
        """Restore weights/counts/experiences written by save().

        save() serializes weights/counts as a LIST of [key, value] pairs
        ([[bucket, action], value]). The previous implementation called
        `.items()` on that list, raising AttributeError which the bare
        `except Exception: pass` swallowed — so memory silently started EMPTY
        on every load and nothing ever persisted across runs. Parse the list
        form (and tolerate a dict for forward/backward compat).
        """
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return  # unreadable/corrupt file -> fresh memory

        def _pairs(raw):
            if isinstance(raw, dict):
                return raw.items()
            return [(k, v) for k, v in (raw or [])]

        self.weights = defaultdict(float, {
            tuple(k): float(v) for k, v in _pairs(data.get("weights"))
        })
        self.counts = defaultdict(int, {
            tuple(k): int(v) for k, v in _pairs(data.get("counts"))
        })
        self.experiences = [
            (b, a, float(r), nb, ok)
            for (b, a, r, nb, ok) in (data.get("experiences") or [])
        ]

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({
                    "weights": [[list(k), v] for k, v in self.weights.items()],
                    "counts": [[list(k), v] for k, v in self.counts.items()],
                    "experiences": [[b, a, r, nb, ok] for (b, a, r, nb, ok) in self.experiences[-500:]],
                }, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ---- core API ----
    def value(self, bucket: str, action: str) -> float:
        return self.weights.get((bucket, action), 0.0)

    def record(self, state: dict, action: str, reward: float, next_state: dict, outcome_kind: str = "OK"):
        """Append a full experience tuple: (bucket, action, reward, next_bucket,
        outcome_kind). This is the agent's actual memory — what it did, what
        happened, what it got. The value table is derived from these."""
        bucket = _bucket(state)
        next_bucket = _bucket(next_state)
        self.experiences.append((bucket, action, round(reward, 4), next_bucket, outcome_kind))

    def max_q(self, state: dict) -> float:
        """max_a' Q(bucket(state), a') over the full action set — TD bootstrap target.

        Standard Q-learning takes the max over ALL actions (not just the current
        candidates), so the value of a state reflects the best thing the agent
        COULD do next, even if that action isn't reachable right now.
        """
        bucket = _bucket(state)
        return max((self.value(bucket, a) for a in self.ACTIONS), default=0.0)

    def update(self, state: dict, action: str, reward: float, next_state: dict = None, outcome_kind: str = "OK"):
        """Record one (state, action, reward, next_state) and shift the value estimate.

        TD(0) / Q-learning update (NOT contextual bandit):
            Q(s,a) <- Q(s,a) + α [ r + γ·max_a' Q(s',a') − Q(s,a) ]

        `next_state` is REQUIRED for the bootstrap term. If it is None (caller
        didn't pass it), we degrade gracefully to a bandit-style update
        (γ·max=0) instead of silently dropping the sequential-learning signal —
        honest fallback, not a silent no-op.
        """
        bucket = _bucket(state)
        key = (bucket, action)
        self.counts[key] += 1
        w = self.weights[key]
        if next_state is not None:
            bootstrap = self.gamma * self.max_q(next_state)
        else:
            bootstrap = 0.0
        target = reward + bootstrap
        self.weights[key] = w + self.lr * (target - w)
        # slow decay of all weights so very old lessons fade (keeps policy adaptive)
        for k in self.weights:
            self.weights[k] *= self.decay
        # record the experience for real memory / analysis
        if next_state is not None:
            self.record(state, action, reward, next_state, outcome_kind)
        self.save()

    def candidate_values(self, state: dict, actions: List[str]) -> Dict[str, float]:
        bucket = _bucket(state)
        return {a: self.value(bucket, a) for a in actions}

    def snapshot(self) -> dict:
        """Human-readable view of what the agent has learned (for logging/debug)."""
        out = {}
        for (bucket, action), w in self.weights.items():
            if abs(w) < 0.05:
                continue
            out.setdefault(bucket, {})[action] = round(w, 3)
        return out
