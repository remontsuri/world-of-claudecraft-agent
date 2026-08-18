"""QuestExecutor — autonomous active-quest executor (no PPO, deterministic).

Reframe (user 2026-08-16): questLog is the high-level WorldState. The agent must
UNDERSTAND the quest objective: "I kill forest_wolf to fill 8/8, then STOP and
return to the turn-in NPC" — NOT "chase mobs forever". This is a Quest Objective
Controller, not another combat loop.

State machine (per user mandate):
  QUEST_ACTIVE -> OBJECTIVE -> PROGRESS -> OBJECTIVE_COMPLETE
              -> RETURN_TO_GIVER -> TURN_IN -> VERIFY_DONE -> NEXT_QUEST

Repo-verified facts (src/sim/quests/quest_commands.ts):
- turnInQuest() hard-gates on qp.state === 'ready' (L346) AND NPC within
  INTERACT_RANGE+2 (questNpcFor, L354). The agent MUST be physically at the NPC.
- turnInQuestCore() sets qp.state='done', meta.questsDone.add(qid),
  meta.copper += copperReward, grantXp, emit {type:'questDone'} (L432-461).
  So VERIFY_DONE = qid appears in quests_done AND copper/xp/inventory changed.
- computeQuestState (L72): 'ready' iff qp.state==='ready', else 'active'. The
  'ready' flag is SERVER-authoritative (checkQuestReady flips it when
  counts[i] >= required for every objective). The agent must actually slay the
  target; progress is not declared.

CRITICAL anti-crash rule (learned the hard way):
- A* navPath (_navigate_along_path) on a >~150u distance CRASHES the node server
  (findPlayerPath builds a grid too large, OR the straight-line fallback stalls).
- Plain _navigate_to_coord to a NEARBY point (<=~80u) is STABLE (proven: walking
  to the giver at 4.5,5.5 from spawn 2,-2).
- Therefore: NEVER let the player drift far from the turn-in NPC. Keep a hunt
  radius (HUNT_RADIUS=50u). Before every farm step, if dNpc > HUNT_RADIUS, walk
  back via SHORT _navigate_to_coord. This guarantees the return-to-giver nav is
  always short and never touches the crashing A* path.
"""

from hierarchical_env import (
    HierarchicalWoWEnv, SKILLS, ACT_FORWARD, ACT_TURN_LEFT,
)
from verifiers_py import verify_skill

HP_LOW_FRAC = 0.3
HUNT_RADIUS = 50.0      # max distance from turn-in NPC while farming
RETURN_STEPS = 80       # short-nav budget (stable for <=~80u)
FARM_PER_CALL = 1       # high-level farm calls per loop (tight drift control)

# Explicit FSM states
S_QUEST_ACTIVE = "QUEST_ACTIVE"
S_OBJECTIVE = "OBJECTIVE"
S_PROGRESS = "PROGRESS"
S_OBJECTIVE_COMPLETE = "OBJECTIVE_COMPLETE"
S_RETURN_TO_GIVER = "RETURN_TO_GIVER"
S_TURN_IN = "TURN_IN"
S_VERIFY_DONE = "VERIFY_DONE"
S_NEXT_QUEST = "NEXT_QUEST"
S_DONE = "DONE"


def _hp(info):
    p = info.get("player", {}) or {}
    hp = p.get("hp"); maxhp = p.get("maxHp") or p.get("hpMax")
    if hp is None or not maxhp:
        return 1.0
    return hp / maxhp


def _dist(ax, az, bx, bz):
    return ((ax - bx) ** 2 + (az - bz) ** 2) ** 0.5


def _find_mob(info, target_mob_id):
    """Find a mob of the quest species in the local observation (with coords)."""
    near = info.get("nearby") or []
    exact = [e for e in near
             if (e.get("species") == target_mob_id or e.get("type") == target_mob_id)
             and e.get("kind") == "mob" and not e.get("lootable")]
    if exact:
        return exact[0]
    # fallback: any hostile mob (farm occasionally locks the quest species)
    mobs = [e for e in near if e.get("kind") == "mob" or e.get("type") == "mob"]
    return mobs[0] if mobs else None


def _objective_current(info, qid, otype, tgt):
    """Read live server counts[] for this objective (server-authoritative)."""
    for aq in (info.get("quests", {}).get("active") or []):
        if aq.get("id") != qid:
            continue
        for ao in (aq.get("objectives") or []):
            if ao.get("type") == otype and (ao.get("targetMobId") or ao.get("itemId")) == tgt:
                return ao.get("current")
    return None


class QuestExecutor:
    def __init__(self, env: HierarchicalWoWEnv, max_steps: int = 400):
        self.env = env
        self.max_steps = max_steps
        self.log = []

    # ---- read world state ----
    def read_active_quest(self):
        active = self.env._last_info.get("quests", {}).get("active", []) or []
        # first quest that is active/ready and not done
        for q in active:
            st = q.get("state")
            if st in ("active", "ready", "complete"):
                return q
        return None

    def get_objectives(self, q):
        return q.get("objectives") or []

    def choose_objective_target(self, q):
        objs = self.get_objectives(q)
        for o in objs:
            if (o.get("current") or 0) < (o.get("required") or 0):
                return o
        return None

    # ---- core: execute one objective with HARD STOP ----
    def execute_objective(self, q, o):
        """Farm the objective target until counts>=required, staying near the NPC.

        HARD STOP: the moment current>=required, return True WITHOUT another
        farm call — even if 100 mobs are nearby. This is the Quest Objective
        Controller behaviour the user demanded (no infinite pursuit).

        Anti-crash: farm runs in SHORT sessions (FARM_SESSION calls of env.step(0)),
        then we re-check distance to the NPC. The farm skill (target_nearest +
        pursuit) drifts the player; bounding each session keeps the drift small
        (<~60u) so the return nav (A* on <150u, or short _navigate_to_coord) never
        touches the server-crashing long-distance path.
        """
        qid = q.get("id")
        otype = o.get("type")
        tgt = o.get("targetMobId") or o.get("itemId")
        tNpc = q.get("turnInNpc") or {}
        npc_x, npc_z = tNpc.get("x"), tNpc.get("z")
        FARM_SESSION = 5  # env.step(0) calls before re-checking drift/objective

        for _ in range(80):  # high-level iterations (each = one farm session)
            info = self.env._last_info
            cur = _objective_current(info, qid, otype, tgt)
            # HARD STOP — objective fulfilled, do not farm another step
            if cur is not None and cur >= (o.get("required") or 0):
                self.log.append(f"  [hard-stop] {qid} {otype} current={cur}/{o.get('required')} -> STOP")
                return True

            if _hp(info) < HP_LOW_FRAC:
                self.env.step(7)  # heal
                continue

            px, pz = info.get("player_pos", [0, 0])
            dNpc = _dist(px, pz, npc_x or px, npc_z or pz) if npc_x is not None else 0.0

            # Already drifted too far: walk back BEFORE farming more. A* on the
            # (now small) distance is stable; short _navigate_to_coord is the
            # fallback. This is the only nav call, and it runs when dNpc is still
            # modest because we check every session.
            if npc_x is not None and dNpc > HUNT_RADIUS:
                if tNpc.get("navPath"):
                    self.env._navigate_along_path(tNpc["navPath"], max_steps_per_leg=80)
                else:
                    self.env._navigate_to_coord(npc_x, npc_z, max_steps=RETURN_STEPS)
                continue

            # Farm a short session (bounded drift)
            if otype == "kill":
                for _s in range(FARM_SESSION):
                    cur = _objective_current(self.env._last_info, qid, otype, tgt)
                    if cur is not None and cur >= (o.get("required") or 0):
                        self.log.append(f"  [hard-stop] {qid} {otype} current={cur}/{o.get('required')} -> STOP")
                        return True
                    self.env.step(0)  # stable farm skill
                # State hygiene: loot any corpses. The headless server accumulates
                # entity/mob state across farm calls and DIES around ~250 farm
                # calls; interleaving loot (which clears corpses) keeps it alive
                # far longer (verified: 316+ calls stable vs death at 252).
                corpses = [e for e in (self.env._last_info.get("nearby") or [])
                           if (e.get("type") == "corpse" or e.get("lootable")) and not e.get("looted")]
                if corpses:
                    self.env.step(1)
            elif otype == "collect":
                self.env.step(1)  # loot skill = collect
            else:
                self.env.step(0)
        # budget out
        cur = _objective_current(self.env._last_info, qid, otype, tgt)
        self.log.append(f"  [obj-budget] {qid} {otype} current={cur}/{o.get('required')}")
        return cur is not None and cur >= (o.get("required") or 0)


    def verify_objective_progress(self, q, o):
        """True if EVERY objective of q is at/above required (server-authoritative)."""
        objs = self.get_objectives(q)
        if not objs:
            return False
        for o in objs:
            cur = _objective_current(self.env._last_info, q.get("id"), o.get("type"),
                                     o.get("targetMobId") or o.get("itemId"))
            if cur is None or cur < (o.get("required") or 0):
                return False
        return True

    def navigate_to_turn_in(self, q):
        """Walk back to the turn-in NPC via SHORT nav (player is already near,
        thanks to the anti-drift guard). Returns True if within interact range."""
        tNpc = q.get("turnInNpc") or {}
        if tNpc.get("x") is None:
            return False
        # short, stable nav — no A* (A* on long distance crashes the server)
        return self.env._navigate_to_coord(tNpc["x"], tNpc["z"], max_steps=RETURN_STEPS)

    def verify_turn_in_ready(self, q):
        for aq in (self.env._last_info.get("quests", {}).get("active") or []):
            if aq.get("id") == q.get("id"):
                return bool(aq.get("ready") or aq.get("state") in ("ready", "complete"))
        return False

    def turn_in(self, q):
        """Call turn_in_quest and verify via verifiers_py + direct reward delta."""
        qid = str(q.get("id"))
        before = self.env._last_info
        b_copper = before.get("copper", 0)
        b_xp = before.get("xp", 0)
        b_qd = before.get("quests_done", 0)
        out = self.env.base.turn_in_quest(qid)
        self.env._last_info = out
        v = verify_skill("turn_in_quest", {"before": before, "after": out, "handle": qid})
        a_copper = out.get("copper", b_copper)
        a_xp = out.get("xp", b_xp)
        a_qd = out.get("quests_done", b_qd)
        # direct checks from repo facts (turnInQuestCore adds to questsDone, copper, xp)
        in_done = qid in (out.get("quests", {}).get("done", []) or [])
        reward_changed = (a_copper > b_copper) or (a_xp > b_xp) or (a_qd > b_qd)
        ok = (v == "success") or (in_done and reward_changed)
        self.log.append(
            f"  [turn_in] {qid} verify={v} in_done={in_done} "
            f"copperΔ={a_copper-b_copper} xpΔ={a_xp-b_xp} reward_changed={reward_changed} -> {'OK' if ok else 'FAIL'}"
        )
        return ok

    # ---- driver ----
    def run_quest(self, q):
        state = S_OBJECTIVE
        while True:
            if state == S_OBJECTIVE:
                o = self.choose_objective_target(q)
                if o is None:
                    state = S_OBJECTIVE_COMPLETE
                else:
                    state = S_PROGRESS
            elif state == S_PROGRESS:
                o = self.choose_objective_target(q)
                if o is None:
                    state = S_OBJECTIVE_COMPLETE
                else:
                    done = self.execute_objective(q, o)
                    self.log.append(f"OBJ {q.get('id')}/{o.get('type')} done={done}")
                    state = S_OBJECTIVE if not done else S_OBJECTIVE_COMPLETE
            elif state == S_OBJECTIVE_COMPLETE:
                if self.verify_objective_progress(q, None):
                    state = S_RETURN_TO_GIVER
                else:
                    # re-run any incomplete objective
                    state = S_OBJECTIVE
            elif state == S_RETURN_TO_GIVER:
                arrived = self.navigate_to_turn_in(q)
                self.log.append(f"  [return] arrived={arrived}")
                state = S_TURN_IN
            elif state == S_TURN_IN:
                ready = self.verify_turn_in_ready(q)
                if not ready:
                    # not ready yet — shouldn't happen if objectives complete, but
                    # re-run objective loop defensively
                    self.log.append(f"  [turn_in] not ready, re-checking objectives")
                    state = S_OBJECTIVE
                    continue
                ok = self.turn_in(q)
                state = S_VERIFY_DONE if ok else S_OBJECTIVE
            elif state == S_VERIFY_DONE:
                # confirm quest is gone from active and present in done
                still_active = any(
                    aq.get("id") == q.get("id")
                    for aq in (self.env._last_info.get("quests", {}).get("active") or [])
                )
                in_done = q.get("id") in (self.env._last_info.get("quests", {}).get("done", []) or [])
                if in_done and not still_active:
                    self.log.append(f"QUEST DONE: {q.get('id')} (verified in quests_done)")
                    return True
                if not still_active:
                    self.log.append(f"QUEST DONE: {q.get('id')} (left active)")
                    return True
                self.log.append(f"  [verify] {q.get('id')} still active, retry turn_in")
                state = S_TURN_IN
            else:
                return False

    def run(self):
        for step in range(self.max_steps):
            q = self.read_active_quest()
            if q is None:
                self.log.append("NO ACTIVE QUEST — done")
                return "\n".join(self.log[-20:])
            # heal takes priority even between quests
            if _hp(self.env._last_info) < HP_LOW_FRAC:
                self.env.step(7)
                continue
            ok = self.run_quest(q)
            if ok:
                # move to NEXT_QUEST
                nxt = self.read_active_quest()
                if nxt is None:
                    self.log.append("ALL QUESTS DONE")
                    return "\n".join(self.log[-20:])
                # else loop continues with the next active quest
        return "STEP BUDGET REACHED\n" + "\n".join(self.log[-20:])


if __name__ == "__main__":
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
    obs, info = env.reset(seed=42)
    # accept the welcome quest if not already active (headless needs the giver)
    if not info.get("quests", {}).get("active"):
        giver = None
        for _ in range(24):
            env.base.step(ACT_FORWARD); env.base.step(ACT_TURN_LEFT)
            near = env._last_info.get("nearby") or []
            g = [e for e in near if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
            if g:
                giver = g[0]; break
        if giver:
            qid = (giver.get("questIds") or [None])[0]
            env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
            env.base.accept_quest(str(qid))
            env._last_info = env.base.accept_quest(str(qid))
    print("ACTIVE QUESTS:", [q.get("id") for q in env._last_info.get("quests", {}).get("active", [])])
    ex = QuestExecutor(env, max_steps=400)
    print(ex.run())
    env.close()
