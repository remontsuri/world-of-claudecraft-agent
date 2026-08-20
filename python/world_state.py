"""world_state.py — SINGLE source of truth for the agent's WorldState.

Why this file exists (bug found 2026-08-17, measured by _diag_bucket.py):

`policy.GoalManager._world_state()` and `agent._world_state_dict()` each built
their OWN partial state dict, and BOTH were fed to `memory._bucket()`:

  decide() bucket : hp=full|qs=NONE|mob=1|corpse=1|junk=1|danger=0|far=0|combat=0
  learn()  bucket : hp=full|qs=NONE|mob=0|corpse=0|junk=0|danger=0|far=1|combat=0

The policy state had no `distance_to_giver`/`in_combat` (so `far`/`combat` were
pinned to 0), and the agent state had no `has_mob`/`has_corpse`/`has_junk`/
`danger` (so those were pinned to 0). Consequence, measured: a lesson written
with value -0.999 under the learn() key was read back as +0.000 by the decide()
key. Every lesson was filed under a bucket the decision path never looked up —
so learning COULD NOT change behaviour, and P(action|far) could never move for
the far bucket.

This also invalidates the earlier "P(return|far) 0 -> 0.15" reading: that was
measured by filtering on the observed distance, while the policy was actually
reading a far=0 bucket. The shift was a confound, not a lesson about distance.

Fix: build the FULL state once, here, and use it for candidates, bucketing and
reward. Fields are OBSERVATIONS (measured facts), never rules.
"""

from typing import Dict


def build_world_state(info: Dict) -> Dict:
    """Flatten env info into the complete WorldState.

    Superset of what three consumers need:
      - memory._bucket(): hp_frac, quest_status, has_mob, has_corpse, has_junk,
        danger, distance_to_giver, in_combat
      - policy._candidates(): hp_frac (+ raw info for entity lists)
      - reward.outcome_reward(): xp, copper, kills, quests_done, deaths,
        inv_slots, quest_progress, distance_to_giver
    """
    p = info.get("player", {}) or {}
    hp = p.get("hp")
    maxhp = p.get("maxHp") or p.get("hpMax") or 1
    hp_frac = (hp / maxhp) if hp is not None else 1.0

    nearby = info.get("nearby") or []
    has_mob = any(
        (e.get("kind") == "mob" or e.get("type") == "mob") and not e.get("lootable")
        for e in nearby
    )
    has_corpse = any(
        (e.get("type") == "corpse" or e.get("kind") == "corpse" or e.get("lootable"))
        and not e.get("looted")
        for e in nearby
    )

    inv = info.get("inventory") or []
    has_junk = any((i.get("quality") or 0) == 0 for i in inv)

    # vendor proximity: is a vendor NPC within interact range? Drives sell_junk
    # candidacy in policy (no point offering sell_junk when the vendor is far,
    # since navigate_to_vendor does not exist and the bridge no-ops the call).
    ppos = info.get("player_pos") or [0, 0]
    vendor_nearby = any(
        (e.get("kind") == "npc" or e.get("type") == "npc")
        and (e.get("vendor") or e.get("vendorItems") or e.get("isVendor"))
        and ((e.get("x", 0) - ppos[0]) ** 2 + (e.get("z", 0) - ppos[1]) ** 2) ** 0.5 <= 12
        for e in nearby
    )

    # quest facts: progress, status, and MEASURED distance to the turn-in NPC
    quest_progress = 0
    distance_to_giver = 999.0
    quest_status = "NONE"
    active = info.get("quests", {}).get("active") or []
    ready = info.get("quests", {}).get("ready") or []
    all_q = active + ready
    if all_q:
        any_incomplete = False
        for q in all_q:
            for o in (q.get("objectives") or []):
                cur = o.get("current") or 0
                req = o.get("required") or 0
                quest_progress += min(cur, req)
                if cur < req:
                    any_incomplete = True
            tNpc = q.get("turnInNpc") or {}
            if tNpc.get("x") is not None:
                px, pz = info.get("player_pos", [0, 0])
                d = ((tNpc["x"] - px) ** 2 + (tNpc["z"] - pz) ** 2) ** 0.5
                # keep the CLOSEST turn-in NPC, not the last one iterated
                if d < distance_to_giver:
                    distance_to_giver = d
        quest_status = "ACTIVE" if any_incomplete else "READY_TO_TURN_IN"

    in_combat = bool(info.get("in_combat"))
    dead = bool(p.get("dead"))
    danger = dead or (hp_frac < 0.3) or in_combat

    return {
        # bucket features (observations)
        "hp_frac": hp_frac,
        "quest_status": quest_status,
        "has_mob": has_mob,
        "has_corpse": has_corpse,
        "has_junk": has_junk,
        "vendor_nearby": vendor_nearby,
        "danger": danger,
        "distance_to_giver": distance_to_giver,
        "in_combat": in_combat,
        "dead": dead,
        # reward counters (deltas computed by reward.outcome_reward)
        "kills": info.get("kills", 0),
        "xp": info.get("xp", 0),
        "copper": info.get("copper", 0),
        "quests_done": info.get("quests_done", 0),
        "deaths": info.get("deaths", 0),
        "inv_slots": len(inv),
        "quest_progress": quest_progress,
    }
