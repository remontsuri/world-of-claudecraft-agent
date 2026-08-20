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
import os
import tempfile
import math
import traceback
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

    def __init__(self, lr: float = 0.2, decay: float = None, gamma: float = 0.9, path: Optional[str] = None):
        # (bucket, action) -> float value estimate
        self.weights: Dict[Tuple[str, str], float] = defaultdict(float)
        # (bucket, action) -> count (for confidence / exploration bonus)
        self.counts: Dict[Tuple[str, str], int] = defaultdict(int)
        # experience log: (bucket, action, reward, next_bucket, outcome_kind)
        # This is the REAL memory the user wants: not "farm is bad" but
        # "in a similar state I did farm -> X happened -> -0.48 -> P(farm) dropped".
        self.experiences: List[Tuple[str, str, float, str, str]] = []
        self.lr = lr
        # `decay` is accepted for backward compatibility but NO LONGER APPLIED.
        # Per-step decay exponentially erased all lessons (incl. good ones) by
        # absolute step count, which conflicted with "learn across sessions".
        # Tabular Q-learning is adaptive on its own via the TD update above.
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
        """Atomically persist memory. Write to a temp file in the same directory
        then os.replace() (atomic rename on Windows) so a kill/restart mid-write
        can never leave a truncated/corrupt file that silently wipes all learned
        experience on next load (the old code wrote directly and swallowed
        errors with `except: pass`, losing the whole store)."""
        try:
            data = {
                "weights": [[list(k), v] for k, v in self.weights.items()],
                "counts": [[list(k), v] for k, v in self.counts.items()],
                "experiences": [[b, a, r, nb, ok] for (b, a, r, nb, ok) in self.experiences[-500:]],
            }
            d = os.path.dirname(os.path.abspath(self.path)) or "."
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".mem_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    try:
                        open(os.path.join(d, "_mem.log"), "a", encoding="utf-8").write("SAVE START %s\n" % time.time())
                    except Exception:
                        pass
                    json.dump(data, f, ensure_ascii=False, indent=1)
                    try:
                        open(os.path.join(d, "_mem.log"), "a", encoding="utf-8").write("SAVE DONE %s\n" % time.time())
                    except Exception:
                        pass
                os.replace(tmp, self.path)  # atomic on Windows
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception:
            # Last-resort guard: never crash the learning loop on a save failure,
            # but DO NOT silently eat the error — surface it.
            traceback.print_exc()

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

    def max_q(self, state: dict, actions: Optional[List[str]] = None) -> float:
        """max_a' Q(bucket(state), a') for the TD bootstrap target.

        Standard Q-learning takes the max over the ACTIONS reachable in the next
        state. If `actions` is provided (the next state's candidate set), we max
        only over those — so an unreachable action (e.g. farm when no mob is near)
        can't inflate the bootstrap. When None (caller doesn't know candidates),
        we fall back to the full ACTIONS set for backward compatibility.
        """
        bucket = _bucket(state)
        acts = actions if actions else self.ACTIONS
        return max((self.value(bucket, a) for a in acts), default=0.0)

    def update(self, state: dict, action: str, reward: float, next_state: dict = None,
               outcome_kind: str = "OK", candidates: Optional[List[str]] = None):
        """Record one (state, action, reward, next_state) and shift the value estimate.

        TD(0) / Q-learning update (NOT contextual bandit):
            Q(s,a) <- Q(s,a) + α [ r + γ·max_a' Q(s',a') − Q(s,a) ]

        `next_state` is REQUIRED for the bootstrap term. If it is None (caller
        didn't pass it), we degrade gracefully to a bandit-style update
        (γ·max=0) instead of silently dropping the sequential-learning signal —
        honest fallback, not a silent no-op.

        `candidates` is the next state's available action set; when provided the
        bootstrap maxes only over reachable actions (see max_q).
        """
        bucket = _bucket(state)
        key = (bucket, action)
        self.counts[key] += 1
        w = self.weights[key]
        if next_state is not None:
            bootstrap = self.gamma * self.max_q(next_state, candidates)
        else:
            bootstrap = 0.0
        target = reward + bootstrap
        self.weights[key] = w + self.lr * (target - w)
        # NOTE: no per-step decay. Tabular Q-learning is already adaptive — new
        # experience re-estimates Q(bucket,action), pushing out old lessons on
        # its own. Per-step decay multiplied EVERY weight by <1 each update,
        # exponentially erasing ALL lessons (good ones included) by absolute step
        # count, which conflicts with "learn across sessions". If stale lessons
        # ever dominate, add an explicit age-based consolidate() instead.
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


# ---- World Memory: persistent quest-giver / vendor knowledge -----------------
# SINGLE SOURCE OF TRUTH for "where does quest X get turned in" and "where is the
# vendor". The live game does NOT expose sim.questDefs/sim.npcDefs, and the server
# does not return giverId inside sim.questLog — so the agent must ACQUIRE this
# knowledge at accept time (it knows the NPC + questId + NPC position) and persist
# it. FARSHORE_* static tables in the bridge are only a FALLBACK when this memory
# is empty (e.g. first run, or a zone with no prior knowledge).
class WorldMemory:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(os.path.dirname(__file__), "world_memory.json")
        # quest_id -> {giver_id, giver_pos:{x,z}, zone, last_seen}
        self.quest_givers: Dict[str, dict] = {}
        # npc_id -> {pos:{x,z}, last_seen}
        self.vendors: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.quest_givers = data.get("quest_givers", {}) or {}
            self.vendors = data.get("vendors", {}) or {}
        except Exception:
            return  # unreadable -> fresh world memory

    def save(self):
        try:
            data = {
                "quest_givers": self.quest_givers,
                "vendors": self.vendors,
            }
            d = os.path.dirname(os.path.abspath(self.path)) or "."
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".wm_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)  # atomic on Windows
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception:
            traceback.print_exc()

    def remember_giver(self, quest_id: str, giver_id: str, giver_pos: dict, zone: str = "farshore"):
        """Record (or refresh) the turn-in NPC for a quest."""
        if not quest_id:
            return
        self.quest_givers[str(quest_id)] = {
            "giver_id": str(giver_id) if giver_id else None,
            "giver_pos": {"x": giver_pos.get("x"), "z": giver_pos.get("z")}
                        if isinstance(giver_pos, dict) else None,
            "zone": zone,
            "last_seen": time.time(),
        }

    def giver_pos(self, quest_id: str) -> Optional[dict]:
        """Return {x,z} for the turn-in NPC of a quest, or None if unknown."""
        g = self.quest_givers.get(str(quest_id))
        if g and g.get("giver_pos"):
            return g["giver_pos"]
        return None

    def remember_vendor(self, npc_id: str, pos: dict, zone: str = "farshore"):
        if not npc_id:
            return
        self.vendors[str(npc_id)] = {
            "pos": {"x": pos.get("x"), "z": pos.get("z")} if isinstance(pos, dict) else None,
            "zone": zone,
            "last_seen": time.time(),
        }

    def vendor_pos(self, npc_id: str) -> Optional[dict]:
        v = self.vendors.get(str(npc_id))
        if v and v.get("pos"):
            return v["pos"]
        return None
