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


def turn_in_quest(env, ctx: dict, world_mem=None) -> str:
    """Walk to turn-in NPC (short nav) and call turn_in_quest. Returns
    SUCCESS / PARTIAL (couldn't reach) / FAILURE.

    Fix3 (2026-08-23): the live questLog reports `turnInNpc: null` for every
    quest in this build, so navigation used to fail before taking a step.
    WorldMemory persists giver positions per quest id — backfill the target
    from there when the live snapshot has none. A READY quest is the
    preferred target (it is the one that CAN be turned in)."""
    cap = QuestCapability(env)
    q = ctx.get("quest")
    if q is None:
        q = cap.find_ready_quest() or cap.find_active_quest()
    if q is None:
        return "FAILURE"
    tNpc = q.get("turnInNpc") or {}
    if tNpc.get("x") is None:
        qid = q.get("id") or q.get("questId")
        pos = world_mem.giver_pos(qid) if (world_mem is not None and qid) else None
        if pos is None:
            # live nearby fallback: the NPC offering/owning this quest IS the giver
            for e in ((getattr(env, "_last_info", None) or {}).get("nearby") or []):
                ids = e.get("questIds") or []
                if qid and qid in ids and e.get("x") is not None:
                    pos = {"x": e["x"], "z": e["z"]}
                    break
        if pos:
            q["turnInNpc"] = {"x": pos["x"], "z": pos["z"]}
    res = cap.navigate_to_turn_in(q)
    if res != "SUCCESS":
        return "PARTIAL"
    return cap.turn_in(q)


RETURN_STEP_BUDGET = 80  # one leg per call -> each call is measurable, but large
                        # enough that a single call actually closes real distance
                        # (25 was too short: the agent never reached the giver in
                        # one call, so return got no positive dist_progress and
                        # learned a negative lesson — see experiment_b3_control trace)



def return_to_giver(env, ctx: dict, world_mem=None) -> str:
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
    qid = q.get("id") or q.get("questId")

    # Giver position priority (per audit 2026-08-20):
    #   1. Persistent WorldMemory (learned at accept time) — PRIMARY source.
    #      The live game does NOT expose giverId/turnInNpc reliably in sim.questLog,
    #      so we must NOT depend on the snapshot for the turn-in location.
    #   2. Live snapshot turnInNpc — fallback when memory has no entry yet.
    #   FARSHORE static tables live in browser_bridge.cjs and are only consulted
    #   there when the NPC is not loaded into sim.entities; they are NOT read here.
    giver_pos = None
    if world_mem is not None and qid:
        giver_pos = world_mem.giver_pos(qid)
    if giver_pos is None:
        tNpc = q.get("turnInNpc") or {}
        if tNpc.get("x") is not None:
            giver_pos = {"x": tNpc["x"], "z": tNpc["z"]}
    # 2026-08-23 fallback: scan nearby NPCs whose questIds include this quest —
    # the live snapshot maps quest->NPC even when turnInNpc/memory are empty
    # (measured: kitchens had NO memory entry and null turnInNpc -> 35 FAILs).
    if giver_pos is None and qid:
        for e in (env._last_info.get("nearby") or []):
            ids = e.get("questIds") or []
            if qid in ids and e.get("x") is not None:
                giver_pos = {"x": e["x"], "z": e["z"]}
                break
    if giver_pos is None or giver_pos.get("x") is None:
        return "FAILURE"

    px, pz = env._last_info.get("player_pos", [0, 0])
    d0 = ((giver_pos["x"] - px) ** 2 + (giver_pos["z"] - pz) ** 2) ** 0.5

    # Navigate DIRECTLY toward the turn-in NPC (giver). We deliberately ignore the
    # server's navPath waypoints: in this environment those waypoints can point
    # sideways/away from the giver, so following them made return_to_giver INCREASE
    # distance (measured M3 Δdist = +61 for budget=80). Going straight at the giver
    # is the honest "walk back" the Policy is supposed to learn is useful.
    # 2026-08-23: primary walker = geometric raw_move legs (nav_policy) with
    # fence-hop pulses; the scripted bridge navigate stays as fallback when the
    # walker cannot run (no facing info).
    # 2026-08-24: nav_policy.execute шлёт СЕРИИ raw_move(turnLeft/turnRight), и
    # каждый такой вызов — отдельный рывок камеры. Пользователь видел именно это
    # («агент постоянно водит камерой из стороны в сторону»). Возвращаемся к
    # мостовому navigateToCoord: там ОДИН персистентный ввод с гистерезисом
    # (см. TURN_HELPER в actions.cjs), камера не дрожит.
    arrived = env._navigate_to_coord(giver_pos["x"], giver_pos["z"],
                                     max_steps=RETURN_STEP_BUDGET)

    px2, pz2 = env._last_info.get("player_pos", [0, 0])
    d1 = ((giver_pos["x"] - px2) ** 2 + (giver_pos["z"] - pz2) ** 2) ** 0.5
    if d1 < 6:
        return "SUCCESS"
    # Mid-chain: the leg ran but the giver is not reached yet. reward.py scores
    # the MEASURED distance delta (d0 -> d1), so PARTIAL is correct whether we
    # closed or drifted distance this call. (Old code had a dead `if d1 < d0
    # else PARTIAL` — both branches returned PARTIAL; collapsed to one return.)
    return "PARTIAL"


def sell_junk(env, world_mem=None, max_steps: int = 80) -> str:
    """Sell junk using remembered vendor knowledge.

    This is an atomic capability: it may spend one bounded navigation leg to a
    vendor already learned from the world. It never invents a vendor location.
    Returns SUCCESS when the sell action was issued at vendor range, PARTIAL when
    navigation moved toward a known vendor but did not reach it, FAILURE when no
    vendor is known and none is currently nearby.
    """
    info = env._last_info or {}
    p = info.get("player_pos") or [0, 0]
    px, pz = p[0], p[1]
    nearby = info.get("nearby") or []

    def is_vendor(e):
        return ((e.get("kind") == "npc" or e.get("type") == "npc") and
                (e.get("vendor") or e.get("vendorItems") or e.get("isVendor")))

    # Learn/refresh all visible vendors before choosing a route.
    if world_mem is not None:
        for e in nearby:
            if is_vendor(e) and e.get("id") is not None and e.get("x") is not None:
                world_mem.remember_vendor(str(e["id"]), {"x": e["x"], "z": e["z"]})
        world_mem.save()

    visible = [e for e in nearby if is_vendor(e) and e.get("x") is not None and e.get("z") is not None]
    if visible:
        visible.sort(key=lambda e: ((e["x"]-px)**2 + (e["z"]-pz)**2) ** 0.5)
        d = ((visible[0]["x"]-px)**2 + (visible[0]["z"]-pz)**2) ** 0.5
        if d > 12:
            env._navigate_to_coord(visible[0]["x"], visible[0]["z"], max_steps=max_steps)
        px, pz = env._last_info.get("player_pos", [px, pz])
        d = ((visible[0]["x"]-px)**2 + (visible[0]["z"]-pz)**2) ** 0.5
        if d <= 12:
            env.step(4)
            return "SUCCESS"
        return "PARTIAL"

    # No visible vendor: use persistent memory, nearest known vendor first.
    candidates = []
    if world_mem is not None:
        for npc_id, rec in world_mem.vendors.items():
            pos = (rec or {}).get("pos") or {}
            if pos.get("x") is None or pos.get("z") is None:
                continue
            d = ((pos["x"]-px)**2 + (pos["z"]-pz)**2) ** 0.5
            candidates.append((d, npc_id, pos))
    if not candidates:
        return "FAILURE"
    _, _, pos = min(candidates, key=lambda x: x[0])
    env._navigate_to_coord(pos["x"], pos["z"], max_steps=max_steps)
    info2 = env._last_info or {}
    px2, pz2 = info2.get("player_pos", [px, pz])
    # We need a fresh live vendor confirmation before selling; memory alone is
    # location knowledge, not proof that the NPC is currently interactable.
    live = [e for e in (info2.get("nearby") or []) if is_vendor(e) and e.get("x") is not None]
    if live:
        d2 = min(((e["x"]-px2)**2 + (e["z"]-pz2)**2) ** 0.5 for e in live)
        if d2 <= 12:
            env.step(4)
            return "SUCCESS"
    return "PARTIAL"
