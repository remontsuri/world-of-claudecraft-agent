"""QuestSkill (atomic capabilities) — tools, NOT a hidden GoalManager.

Per user 2026-08-16: QuestSkill must NOT decide "ACTIVE -> farm" internally. That
is the Policy's job. Here QuestSkill is a set of ATOMIC tools the Policy composes:
  - complete_quest_objective(ctx): ONE short attempt at the current objective
    (farm one burst / loot one corpse). No loop, no "keep farming until done".
  - turn_in_quest(ctx): walk back (short nav, env-safe) + call turn_in_quest.
  - return_to_giver(ctx): just navigate back to the turn-in NPC (short nav).

The Policy chooses WHICH of these (or plain farm/loot/heal/explore) to call, based
on learned weights. QuestSkill only executes; it never orchestrates.

bounded-drift in complete_quest_objective is an ENV SAFETY LIMIT (server crashes on
long-distance nav), NOT a policy rule. The Policy observes distance_to_giver as a
WorldState feature and may learn "don't farm when far" on its own.
"""

from quest_capability import QuestCapability

HUNT_RADIUS = 50.0  # env safety limit, not a policy decision


def complete_quest_objective(env, ctx: dict, max_substeps: int = 12) -> str:
    """ONE attempt at the active quest's first incomplete objective.

    Returns SUCCESS (objective already complete) / PARTIAL (did a burst) /
    FAILURE (no quest / no objective). Does NOT loop — Policy re-invokes next step.
    """
    cap = QuestCapability(env)
    q = ctx.get("quest") or cap.find_active_quest()
    if q is None:
        return "FAILURE"
    o = cap.incomplete_objective(q)
    if o is None:
        return "SUCCESS"  # nothing to do; turn-in is a separate Policy choice
    tNpc = q.get("turnInNpc") or {}
    npc_x, npc_z = tNpc.get("x"), tNpc.get("z")

    # ENV SAFETY LIMIT: if drifted past hunt radius, refuse to farm further and
    # walk back via short nav. (Policy may also choose return_to_giver instead.)
    if npc_x is not None:
        px, pz = env._last_info.get("player_pos", [0, 0])
        dNpc = ((npc_x - px) ** 2 + (npc_z - pz) ** 2) ** 0.5
        if dNpc > HUNT_RADIUS:
            if tNpc.get("navPath"):
                env._navigate_along_path(tNpc["navPath"], max_steps_per_leg=80)
            else:
                env._navigate_to_coord(npc_x, npc_z, max_steps=80)

    # one burst toward the objective
    if (o.get("type") == "collect") or (o.get("itemId") and not o.get("targetMobId")):
        env.step(1)  # loot/collect
    else:
        env.step(0)  # farm (target_nearest + attack)
        # state hygiene: loot corpses to keep the headless server alive
        corpses = [e for e in (env._last_info.get("nearby") or [])
                   if (e.get("type") == "corpse" or e.get("lootable")) and not e.get("looted")]
        if corpses:
            env.step(1)
    return "PARTIAL"


def turn_in_quest(env, ctx: dict) -> str:
    """Walk to turn-in NPC (short nav) and call turn_in_quest. Returns
    SUCCESS / PARTIAL (couldn't reach) / FAILURE."""
    cap = QuestCapability(env)
    q = ctx.get("quest") or cap.find_active_quest()
    if q is None:
        return "FAILURE"
    res = cap.navigate_to_turn_in(q)
    if res != "SUCCESS":
        return "PARTIAL"
    return cap.turn_in(q)


RETURN_STEP_BUDGET = 80  # one leg per call -> each call is measurable, but large
                        # enough that a single call actually closes real distance
                        # (25 was too short: the agent never reached the giver in
                        # one call, so return got no positive dist_progress and
                        # learned a negative lesson — see experiment_b3_control trace)



def return_to_giver(env, ctx: dict) -> str:
    """ONE SHORT leg toward the turn-in NPC. Atomic, measurable, non-terminal.

    Deliberately NOT "walk all the way back". Per user 2026-08-17: the agent
    should learn from a CHAIN of measurable transitions

        far=150 -> return -> far=130 -> return -> far=100 -> ...

    where every single call produces its own measured dist_progress, instead of
    one opaque mega-action whose outcome is all-or-nothing. If the agent instead
    picks explore and ends up at far=180, it gets a real negative consequence.

    Returns SUCCESS when actually within interact range of the giver, PARTIAL when
    the leg ran but the giver is not reached yet (the normal case mid-chain), and
    FAILURE when there is no quest / no known giver position. PARTIAL is not a
    penalty by itself — reward.py scores the MEASURED distance delta.
    """
    cap = QuestCapability(env)
    q = ctx.get("quest") or cap.find_active_quest()
    if q is None:
        return "FAILURE"
    tNpc = q.get("turnInNpc") or {}
    if tNpc.get("x") is None:
        return "FAILURE"

    px, pz = env._last_info.get("player_pos", [0, 0])
    d0 = ((tNpc["x"] - px) ** 2 + (tNpc["z"] - pz) ** 2) ** 0.5

    # Navigate DIRECTLY toward the turn-in NPC (giver). We deliberately ignore the
    # server's navPath waypoints: in this environment those waypoints can point
    # sideways/away from the giver, so following them made return_to_giver INCREASE
    # distance (measured M3 Δdist = +61 for budget=80). Going straight at the giver
    # is the honest "walk back" the Policy is supposed to learn is useful.
    arrived = env._navigate_to_coord(tNpc["x"], tNpc["z"], max_steps=RETURN_STEP_BUDGET)

    px2, pz2 = env._last_info.get("player_pos", [0, 0])
    d1 = ((tNpc["x"] - px2) ** 2 + (tNpc["z"] - pz2) ** 2) ** 0.5
    if d1 < 6:
        return "SUCCESS"
    # Mid-chain: the leg ran but the giver is not reached yet. reward.py scores
    # the MEASURED distance delta (d0 -> d1), so PARTIAL is correct whether we
    # closed or drifted distance this call. (Old code had a dead `if d1 < d0
    # else PARTIAL` — both branches returned PARTIAL; collapsed to one return.)
    return "PARTIAL"
