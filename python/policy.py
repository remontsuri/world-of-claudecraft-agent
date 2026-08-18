"""GoalManager / High-Level Policy — the agent's decision maker.

Per user 2026-08-16: this must NOT be a scripted `if HP<30: heal` bot. It is a
tabular policy whose action weights are learned from experience (see memory.py).
It CAN make mistakes (e.g. pick farm at low HP) — that's how it learns. The
verifier/outcome loop feeds reward back into memory, and bad choices become less
likely over time WITHOUT any hard-coded safety rule.

Decision flow each step:
  1. Build the candidate skill set from CURRENT world state (what's reachable).
  2. Read learned values (state_bucket, action) from ExperienceStore.
  3. Sample an action ~softmax(weights) over candidates (exploration preserved).
  4. Return (skill_name, ctx) — the Skill Library executes it.

Skills are the SAME fixed list as hierarchical_env.SKILLS (farm/loot/accept/
turn_in/heal/...). QuestSkill is just another candidate once a quest is active.

No orchestration: the policy never says "do objective then return to NPC". It only
expresses a preference. The QuestSkill itself uses QuestCapability and returns
SUCCESS/PARTIAL/FAILURE; the policy reacts to that next step.
"""

import math
import random
from typing import Dict, List, Optional, Tuple

from memory import ExperienceStore, _bucket
from world_state import build_world_state

# Skill names (must align with hierarchical_env.SKILLS indices)
SKILL_FARM = "farm"
SKILL_LOOT = "loot"
SKILL_ACCEPT = "accept_quest"
SKILL_TURN_IN = "turn_in_quest"
SKILL_RETURN = "return_to_giver"
SKILL_HEAL = "heal"
SKILL_SELL = "sell_junk"
SKILL_GATHER = "gather"
SKILL_QUEST = "quest"  # legacy alias, no longer a candidate (atomized below)
SKILL_EXPLORE = "explore"  # plain forward walk — lets the agent traverse the world

# Outcome rewards (the agent learns these signs; no hard-coded rules)
REWARD = {
    "quest_progress": 1.0,    # an objective count went up
    "quest_done": 5.0,        # turn-in succeeded
    "loot_gain": 0.5,         # inventory/copper increased via loot
    "kill": 0.3,
    "heal_ok": 0.2,
    "waste": -0.2,            # action did nothing useful
    "death": -5.0,            # agent died
    "drift_far": -0.5,        # wandered far from quest giver (learned bad habit)
}


def _softmax_sample(weights: Dict[str, float], temperature: float = 1.0,
                    counts: Optional[Dict] = None, bucket: Optional[str] = None,
                    exploration_weight: float = 1.0) -> str:
    """Sample an action proportional to exp(w/temp). Falls back to uniform on
    empty/zero weights (pure exploration).

    Exploration: rarely-tried (bucket, action) pairs get an optimistic bonus so the
    agent KEEPS trying them even after a bad lesson — farm must stay possible (P>0),
    never hard-forbidden by a zero weight. This is genuine exploration, not a
    scripted "farm allowed" rule.

    The count key MUST be the real (state_bucket, action) used by ExperienceStore.
    Previously the key was ("explore", action) — never present in the table — so the
    bonus was the same constant for every candidate and cancelled inside the softmax,
    making count-based exploration a silent no-op. `bucket` is now required for the
    bonus to do anything; without it the bonus is skipped entirely (honest uniform
    prior) rather than faked.

    `exploration_weight` (0..1) scales the bonus. Set to 0.0 for MEASUREMENT (frozen
    eval) so P(action) reflects Q only — this removes the exploration/visit-count
    confound when comparing BEFORE vs AFTER choice probabilities. Training keeps 1.0.
    """
    actions = list(weights.keys())
    if not actions:
        raise ValueError("no candidate actions")
    eff = {}
    for a in actions:
        w = weights[a]
        if counts is not None and bucket is not None and exploration_weight > 0.0:
            c = counts.get((bucket, a), 0) or 0
            # optimistic bonus, decays as the pair is actually tried
            w = w + exploration_weight * 0.5 / (1.0 + c * 0.1)
        eff[a] = w
    maxw = max(eff.values())
    exps = {a: math.exp((eff[a] - maxw) / max(temperature, 1e-3)) for a in actions}
    total = sum(exps.values())
    r = random.random() * total
    cum = 0.0
    for a in actions:
        cum += exps[a]
        if r <= cum:
            return a
    return actions[-1]


class GoalManager:
    def __init__(self, memory: ExperienceStore, temperature: float = 1.2, seed: int = None):
        self.mem = memory
        self.temperature = temperature
        if seed is not None:
            random.seed(seed)

    # ---- build WorldState features from env info ----
    def _world_state(self, info: dict) -> dict:
        """Delegate to the SINGLE shared builder.

        This used to build its own partial dict (no distance_to_giver, no
        in_combat), which pinned the bucket's far/combat features to 0 while
        agent._world_state_dict() pinned mob/corpse/junk/danger to 0. The two
        buckets never matched, so lessons were unreadable by the decision path
        (measured by _diag_bucket.py). One builder = one bucket key.
        """
        return build_world_state(info)

    # ---- candidate skills from current world ----
    def _candidates(self, info: dict, ws: dict) -> List[str]:
        near = info.get("nearby") or []
        quest_npcs = [e for e in near
                      if (e.get("kind") == "npc" or e.get("type") == "npc")
                      and (e.get("questIds") or e.get("questId"))]
        corpses = [e for e in near
                   if (e.get("type") == "corpse" or e.get("kind") == "corpse" or e.get("lootable"))
                   and not e.get("looted")]
        mobs = [e for e in near if (e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")]
        inv = info.get("inventory") or []
        junk = [i for i in inv if (i.get("quality") or 0) == 0]
        active = info.get("quests", {}).get("active") or []

        cands = []
        if ws["hp_frac"] < 1.0:
            cands.append(SKILL_HEAL)           # always available, agent may or may not pick it
        if mobs or info.get("targetId") is not None:
            cands.append(SKILL_FARM)
        if corpses:
            cands.append(SKILL_LOOT)
        if quest_npcs:
            cands.append(SKILL_ACCEPT)
        # Atomic quest-related actions. The Policy chooses among these — it is NOT
        # a single "do quest" button. turn_in only when ready; return_to_giver is
        # always an option while a quest is active (agent may learn to use it when
        # drifted far). complete_objective is NOT auto-chosen here — the Policy
        # picks plain FARM for progress (same primitive), keeping the decision
        # explicit.
        if any(q.get("state") in ("ready", "complete") for q in active) or \
           any(all((o.get("current") or 0) >= (o.get("required") or 0)
                    for o in (q.get("objectives") or [])) for q in active):
            cands.append(SKILL_TURN_IN)        # atomic: walk + turn_in
        if active:
            cands.append(SKILL_RETURN)         # atomic: navigate back to giver
        if junk:
            cands.append(SKILL_SELL)
        # explore: plain forward walk — ALWAYS available. This is what lets the
        # agent leave the spawn area and discover NPCs/mobs on its own, instead of
        # standing still when no mob is in `nearby`. It is a genuine capability the
        # policy may learn to use (or not), not a scripted "go explore" rule.
        cands.append(SKILL_EXPLORE)
        # de-dup, preserve order
        seen = set(); out = []
        for c in cands:
            if c not in seen:
                seen.add(c); out.append(c)
        return out

    # ---- main decision ----
    def decide(self, info: dict, ws: dict = None, exploration_weight: float = 1.0) -> Tuple[str, dict]:
        """Choose one skill. `ws` may be passed in by the caller so the decision
        and the later learn() call are guaranteed to use the SAME WorldState
        instance (and therefore the same bucket key). `exploration_weight` scales
        the count-based bonus; pass 0.0 at MEASUREMENT time so P reflects Q only
        (removes the exploration/visit-count confound)."""
        if ws is None:
            ws = self._world_state(info)
        cands = self._candidates(info, ws)
        if not cands:
            return SKILL_FARM, {}
        vals = self.mem.candidate_values(ws, cands)
        # ensure every candidate has an entry (unseen -> 0)
        bucket = _bucket(ws)   # SAME key ExperienceStore uses, so the count-based
                               # exploration bonus actually differentiates candidates
        action = _softmax_sample(vals, self.temperature, counts=self.mem.counts,
                                 bucket=bucket, exploration_weight=exploration_weight)
        # ctx: pass the active quest if relevant
        ctx = {}
        if action in (SKILL_TURN_IN, SKILL_RETURN, SKILL_ACCEPT):
            for q in (info.get("quests", {}).get("active") or []):
                if q.get("state") in ("active", "ready", "complete"):
                    ctx["quest"] = q
                    break
            if action == SKILL_ACCEPT:
                for e in (info.get("nearby") or []):
                    if (e.get("kind") == "npc" or e.get("type") == "npc") and (e.get("questIds") or e.get("questId")):
                        ctx["npc"] = e
                        break
        return action, ctx

    def learn(self, ws: dict, action: str, reward: float, next_state: dict = None, outcome_kind: str = "OK"):
        """Feed an outcome back into memory. ws is the SAME world-state the
        decision was made from (caller passes it). next_state is the resulting
        world-state, recorded as experience (real memory of what happened)."""
        self.mem.update(ws, action, reward, next_state=next_state, outcome_kind=outcome_kind)
