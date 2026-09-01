"""agent.py — the closed learning loop (no orchestrator, no PPO, no Sim edits).

Strict cycle, one decision per call:
  WorldState(before)
    -> GoalManager.decide()      (learned policy + exploration)
    -> Skill (quest_skill / env.step(idx))
    -> Capability API
    -> Game transition
    -> WorldState(after)
    -> Verifier (verify_skill)   (objective truth)
    -> Outcome (SUCCESS/PARTIAL/FAILURE/INCONCLUSIVE/ENV_ERROR)
    -> Reward (from FACT via reward.outcome_reward)
    -> Memory.learn(state, action, reward)

NO `if quest active: do quest`. NO hidden orchestrator. The policy chooses; the
skill executes; memory changes the policy. That's the whole design.

ENV_ERROR (headless server crash) is reported as outcome_kind="ENV_ERROR" and yields
reward 0.0 — it must NOT poison the policy with a false "farm is bad" lesson.

Source of truth for game facts (NPCs, quests, positions, ranges): D:\woc (official
levy-street/world-of-claudecraft). Agent repo MUST NOT duplicate game data — only
caches, normalized snapshots, learned memory, own stats. GameSource (game_source.py)
is the dynamic CDP adapter; static JSON (giver_positions.json) is deprecated.
"""

import os
import sys
import time
import traceback
from browser_env import BrowserBridgeError

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT, SKILLS
from verifiers_py import verify_skill
from policy import GoalManager
from memory import ExperienceStore, _bucket, WorldMemory
from reward import outcome_reward
from world_state import build_world_state
import quest_skill
from quest_capability import QuestCapability
from game_source import GameSource

# P0.3: трассировка горячего цикла за env-гейтом. Раньше _cycle() делал
# 4 безусловных open()+write()+close() в _cycle.log на КАЖДОМ шаге — на
# headless-скорости (296 шагов/сек) это ~1200 открытий файла в секунду.
# WOC_TRACE=1 включает обратно, когда трассировка реально нужна.
_TRACE_ON = os.environ.get("WOC_TRACE", "0") not in ("", "0", "false", "False")
_TRACE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "_cycle.log")
_trace_fh = None


def _trace(msg: str) -> None:
    """Пишет строку трассировки, если WOC_TRACE включён. Держит один открытый
    handle вместо open/close на каждый вызов."""
    if not _TRACE_ON:
        return
    global _trace_fh
    try:
        if _trace_fh is None:
            _trace_fh = open(_TRACE_PATH, "a", encoding="utf-8")
        _trace_fh.write("%.2f %s\n" % (time.time(), msg))
        _trace_fh.flush()
    except Exception:
        pass

# Map skill name -> hierarchical_env action index
SKILL_INDEX = {name: i for i, name in enumerate(SKILLS)}


def _world_state_dict(info: dict, world_mem=None) -> dict:
    """WorldState for reward + memory — delegates to the SINGLE shared builder.

    This used to build its own partial dict (no has_mob/has_corpse/has_junk/
    danger), while policy._world_state() omitted distance_to_giver/in_combat.
    Both were fed to memory._bucket(), so decide() read one key and learn()
    wrote another and no lesson was ever visible to the decision path
    (measured by _diag_bucket.py). One builder = one bucket key.
    """
    return build_world_state(info, world_mem)


class Agent:
    def __init__(self, env: HierarchicalWoWEnv, memory: ExperienceStore, seed=None,
                 world_mem: "WorldMemory" = None, fsm=None, replay=None,
                 strat_mem=None, reflection_hints: dict = None,
                 journal_dir: str = None):
        self.env = env
        self.mem = memory
        self.world_mem = world_mem or WorldMemory()
        # R4 FIX (2026-08-23): hints must reach the LIVE agent. Previously
        # GoalManager was built with no reflection_hints and nothing ever
        # called load_reflection_hints() in production — the hint loop was
        # closed in tests only.
        from policy import load_reflection_hints
        base_dir = journal_dir or os.path.dirname(os.path.abspath(__file__))
        self._journal_dir = base_dir
        hints = dict(reflection_hints or {}) or \
            load_reflection_hints(base_dir)
        self.policy = GoalManager(memory, temperature=1.2, seed=seed,
                                  reflection_hints=hints)
        # P0 №5 / P1 №11 fix: политика получает WorldMemory (vendor positions)
        # и счётчик шагов для stateful buy (cooldown после неудач).
        self.policy.world_mem = self.world_mem
        self.cap = QuestCapability(env)
        # GoalFSM: explicit current_goal, persisted to goal_state.json so an
        # infra restart resumes the in-progress quest instead of NO_QUEST.
        self.fsm = fsm
        if self.fsm is not None:
            self.fsm.world_mem = self.world_mem
        # ReplayBuffer: rare-event-prioritized transitions (not just last).
        self.replay = replay
        # StrategyMemory: per-(quest,skill) success/fail generalizations.
        self.strat_mem = strat_mem
        # Recovery: max respawn attempts per cycle before pausing as ENV_ERROR.
        # 3 is enough to survive a transient healer rejection without burning the
        # whole run; beyond that it is a real recovery failure, not bad luck.
        self.RESPAWN_MAX_ATTEMPTS = 3
        # Dynamic game truth adapter — reads window.__game.sim.worldContent.npcs
        # (91 NPCs with questIds) via CDP. This is the canonical source for giver
        # positions; static giver_positions.json is DEPRECATED. Initialized lazily
        # on first accept_quest so we don't pay CDP connect cost when the agent
        # never needs quests.
        self._game_source = None

    def refresh_hints(self):
        """Reload reflection hints from the journal into the live policy.

        Called by the runner every SAVE_EVERY steps so conclusions drawn at
        runtime (spin:<action>, death:<cell>) steer decisions within seconds,
        not after the next restart.
        """
        from policy import load_reflection_hints
        self.policy.hints = load_reflection_hints(self._journal_dir)
        return self.policy.hints

    def _remember_visible_world(self, info: dict):
        """Persist NPC facts observed by the live browser without steering policy."""
        changed = False
        for e in (info.get("nearby") or []):
            if (e.get("kind") == "npc" or e.get("type") == "npc") and e.get("id") is not None:
                is_vendor = bool(e.get("vendor") or e.get("vendorItems") or e.get("isVendor"))
                if is_vendor and e.get("x") is not None and e.get("z") is not None:
                    self.world_mem.remember_vendor(str(e["id"]), {"x": e["x"], "z": e["z"]})
                    changed = True
        if changed:
            self.world_mem.save()

    def _run_skill(self, action: str, ctx: dict, info_before: dict) -> dict:
        """Execute one skill, return (after_info, verdict, outcome_kind)."""
        try:
            if action == "return_to_giver":
                # atomic: navigate back to the turn-in NPC (short nav, env-safe)
                #   SUCCESS  -> arrived at giver (within interact range)
                #   PARTIAL  -> leg ran but not arrived yet (mid-chain; reward
                #               scores the MEASURED distance delta) -> INCONCLUSIVE
                #   FAILURE  -> no known giver position (world_mem miss AND no
                #               turnInNpc) -> can NEVER navigate. Surface as
                #               FAILURE so the policy learns not to pick it.
                #               Previously ALL non-SUCCESS were mapped to
                #               INCONCLUSIVE, hiding a permanently-stuck return
                #               as if it were a mid-chain partial.
                res = quest_skill.return_to_giver(self.env, ctx, self.world_mem)
                after = self.env._last_info
                if res == "SUCCESS":
                    verdict = "SUCCESS"
                elif res == "FAILURE":
                    verdict = "FAILURE"
                else:
                    verdict = "INCONCLUSIVE"
                return after, verdict, "OK"
            if action == "explore":
                # sustained walk toward nearest mob/NPC (or forward) so the agent
                # actually covers ground. BrowserEnv.explore_walk talks to the
                # online bridge; falls back to a raw forward step elsewhere.
                if hasattr(self.env, "explore_walk"):
                    self.env.explore_walk(steps=10)
                else:
                    self.env.base.step(ACT_FORWARD)
                    # base updated base._last_info; mirror it onto the wrapper so
                    # the after-state reflects the real world, not a stale snapshot.
                    self.env._last_info = getattr(self.env.base, "_last_info", self.env._last_info)
                after = self.env._last_info
                return after, "INCONCLUSIVE", "OK"
            if action == "sell_junk":
                # atomic economy capability: use a live vendor when present or a
                # persistent vendor location learned from prior observations.
                # P1 №7 fix (2026-08-25, regression run PID 8356): SUCCESS ставился
                # по факту вызова env.step(4), без проверки продажи. 2000/2000
                # sell_junk SUCCESS при reward=0.000 -> вырожденная политика.
                # Теперь верифицируем copper-delta как любую мутацию.
                import verifiers_py as _vp
                before_inv = [dict(s) for s in (self.env._last_info or {}).get("inventory", []) or []]
                before_copper = (self.env._last_info or {}).get("copper", 0)
                res = quest_skill.sell_junk(self.env, self.world_mem)
                after = self.env._last_info
                if res == "SUCCESS":
                    v = _vp.verify_skill("sell_junk", {
                        "before": {"player": {"copper": before_copper}, "inventory": before_inv},
                        "after": after,
                    })
                    verdict = v if isinstance(v, str) else str(v)
                    # пустой junk-набор: команда прошла, продавать было нечего ->
                    # это FAILURE выбора (нечего продавать), не inconclusive
                    if verdict == "inconclusive":
                        verdict = "failure"
                elif res == "PARTIAL":
                    verdict = "INCONCLUSIVE"
                else:
                    verdict = "FAILURE"
                return after, verdict, "OK"
            if action == "turn_in_quest":
                # atomic: walk back (short nav) + turn_in. Use QuestCapability path
                # so we get the server-side turn-in + verifier-correct handle.
                # Fix3: world_mem backfills turnInNpc when the live snapshot
                # reports null (it always does in this build).
                res = quest_skill.turn_in_quest(self.env, ctx, self.world_mem)
                after = self.env._last_info
                if res == "SUCCESS":
                    verdict = "SUCCESS"
                elif res == "PARTIAL":
                    verdict = "INCONCLUSIVE"
                else:
                    verdict = "FAILURE"
                return after, verdict, "OK"
            else:
                # standard skill via hierarchical env (farm/loot/heal/accept/sell/gather)
                # Contract (skill_contracts.py): accept_quest = navigate_to_giver ->
                # acceptQuest -> verify_quest_log. The bridge's acceptQuest is a no-op
                # unless the player is already in INTERACT_RANGE, so we MUST walk to the
                # giver first. Coordinates come from the LIVE snapshot (info.nearby), NOT
                # ctx (policy does not guarantee ctx["npc"]["x"/"z"]).
                if action == "accept_quest":
                    import sys as _sys
                    _sys.stderr.write("\n[AGENT accept_quest] === START ===\n")
                    _sys.stderr.write("[AGENT accept_quest] ctx keys: %r\n" % list(ctx.keys()))
                    _sys.stderr.write("[AGENT accept_quest] ctx.npcId=%r ctx.questId=%r\n" % (ctx.get("npcId"), ctx.get("questId")))
                    _sys.stderr.write("[AGENT accept_quest] ctx[npc]=%r\n" % str((ctx.get("npc") or {}))[:200])
                    _json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "giver_positions.json")
                    _fsm = getattr(self, "fsm", None)
                    _qg = getattr(_fsm, "quest_giver", None) if _fsm is not None else None
                    _giver_id = (ctx.get("npcId")
                                 or (ctx.get("npc") or {}).get("id")
                                 or (_qg.get("id") if isinstance(_qg, dict) else None))
                    _nearby = (info_before.get("nearby") if isinstance(info_before, dict)
                               else (self.env._last_info or {}).get("nearby")) or []
                    _npcs_with_quests = [e for e in _nearby if isinstance(e, dict) and (e.get("questIds") or e.get("questId"))]
                    _sys.stderr.write("[AGENT accept_quest] giver_id=%r nearby_n=%d npcs_with_quests=%d\n" % (_giver_id, len(_nearby), len(_npcs_with_quests)))
                    for _qn in _npcs_with_quests[:3]:
                        _sys.stderr.write("  [AGENT nearby qnpc] %s id=%s dist=%s questIds=%s\n" % (_qn.get("name"), _qn.get("id"), _qn.get("dist"), _qn.get("questIds")))
                    if not hasattr(self, "_giver_positions"):
                        try:
                            import json as _json
                            with open(_json_path, "r", encoding="utf-8") as _f:
                                self._giver_positions = _json.load(_f)
                        except Exception:
                            self._giver_positions = {}
                    _pp = (info_before.get("player_pos") if isinstance(info_before, dict) else None) or (self.env._last_info or {}).get("player_pos") or [0, 0]
                    _quest_id = ctx.get("questId") or (ctx.get("npc") or {}).get("questIds", [None])[0]
                    _gs = getattr(self, "_game_source", None)
                    if _gs is None:
                        try:
                            _gs = GameSource()
                            _gs.connect()
                            self._game_source = _gs
                        except Exception:
                            _gs = None
                    _tNpc_coords = None
                    _q = ctx.get("quest")
                    if isinstance(_q, dict):
                        _tNpc = _q.get("turnInNpc") or {}
                        if _tNpc.get("x") is not None:
                            _tNpc_coords = (_tNpc.get("x"), _tNpc.get("z"))
                    _gpos = resolve_giver_pos(
                        _quest_id, _giver_id, _nearby, _qg, getattr(self, "world_mem", None),
                        getattr(self, "_giver_positions", {}), _pp,
                        game_source=_gs,
                        turnInNpc_coords=_tNpc_coords)
                    _sys.stderr.write("[AGENT accept_quest] gpos=%r json_givers_count=%d quest_id=%r\n" % (_gpos, len(getattr(self, "_giver_positions", {})), _quest_id))
                    if _gpos is not None:
                        try:
                            _arrived = self.env._navigate_to_coord(_gpos[0], _gpos[1], max_steps=80)
                        except Exception:
                            pass  # best-effort; accept_quest reports honestly if still far
                    if _gpos is None:
                        # Giver not visible in the live snapshot (out of scan
                        # range). Standing still and calling acceptQuest is a
                        # guaranteed INCONCLUSIVE loop. Instead, walk the world
                        # to bring a giver into view — the Policy will learn that
                        # accept_quest with no visible giver is a no-op and stop
                        # selecting it in empty zones (self-correction loop).
                        try:
                            self.env.explore_walk(steps=12)
                        except Exception:
                            pass
                        return info_before, "FAILURE", "OK"
                idx = SKILL_INDEX.get(action)
                if idx is None:
                    return info_before, "FAILURE", "OK"
                before = info_before
                if action == "accept_quest":
                    import sys as _sys
                    _sys.stderr.write("[AGENT accept_quest] payload to bridge: idx=%d ctx=%r\n" % (idx, {k: ctx.get(k) for k in ["npcId", "questId", "quest", "npc"]}))
                self.env.step(idx, ctx)
                after = self.env._last_info
                if action == "accept_quest":
                    import sys as _sys
                    _sys.stderr.write("[AGENT accept_quest] bridge returned: giver=%r\n" % (getattr(self.env, "last_giver", None)))
                # Persist the turn-in NPC in WorldMemory when we just accepted a quest.
                # The live game does NOT return giverId in sim.questLog, so this is
                # the ONLY place the agent acquires "quest X -> NPC Y at (x,z)".
                # FARSHORE_* static tables in the bridge are only a fallback when this
                # memory is empty. (Acceptance test #1 depends on this.)
                if action == "accept_quest" and getattr(self.env, "last_giver", None):
                    lg = self.env.last_giver
                    qid = lg.get("questId") or (ctx.get("quest") or {}).get("id") or ctx.get("questId")
                    gid = lg.get("giverId")
                    gpos = lg.get("giverPos")
                    if qid and gid:
                        self.world_mem.remember_giver(str(qid), str(gid), gpos or {})
                        self.world_mem.save()
                # verifier (objective truth)
                handle = None
                if action == "turn_in_quest" and ctx.get("quest"):
                    handle = str(ctx["quest"].get("id"))
                elif action == "accept_quest" and ctx.get("npc"):
                    qids = ctx["npc"].get("questIds") or ctx["npc"].get("questId") or [None]
                    handle = str(qids[0]) if qids else None
                elif action == "gather":
                    # 2026-08-24: мост сообщает noTarget, когда у gather не было
                    # ни узла, ни трупа. Верификатор превращает это в честный
                    # failure (иначе агент бьёт в пустоту без сигнала обучения).
                    no_target = bool(getattr(self.env, "_last_handle_no_target", False))
                    handle = {"noTarget": no_target}
                    try:
                        self.env._last_handle_no_target = False
                    except Exception:
                        pass
                elif action == "buy":
                    # 2026-08-25 (buy saturation fix): verify_buy требует itemId
                    # из handle. Без него i0/i1 считались по всей сумке и вердикт
                    # был всегда 'inconclusive' -> 150/150 спамов без урока.
                    handle = {"itemId": ctx.get("buyItemId")}
                v = verify_skill(action, {"before": before, "after": after, "handle": handle})
                verdict = v if isinstance(v, str) else str(v)
                return after, verdict, "OK"
        except BrowserBridgeError:
            # Infra failure (bridge/CDP/HTTP down or rejected the request) — NOT a
            # game outcome, NOT a programming bug. Treat as ENV_ERROR so the loop
            # recovers (reconnect/restart) without poisoning memory with a false
            # lesson. This is the ONLY exception _run_skill swallows.
            return info_before, "FAILURE", "ENV_ERROR"
        # Any OTHER exception (NameError/KeyError/TypeError/AttributeError/
        # AssertionError/RuntimeError from policy/skill/reward) is a PROGRAMMING
        # BUG. It MUST propagate — crash loudly with a traceback so it is fixed,
        # never masked as ENV_ERROR (which would hide a broken agent for hours).

    def step(self) -> dict:
        """One full learning-cycle iteration."""
        return self._cycle(learn=True)

    def step_forced(self, action: str, learn: bool = True) -> dict:
        """Controlled training probe: execute ONE specific action (real world
        effect), compute reward from fact, optionally learn.

        Used ONLY as an explicit training intervention — e.g. to obtain the
        first real (S, action, negative) experience when the autonomous policy
        hasn't chosen that action yet. NEVER used inside the BEFORE/AFTER
        evaluation (which must stay autonomous + frozen). The RESULT still comes
        from the real world; only the CHOICE is forced.
        """
        info_before = self.env._last_info
        self._remember_visible_world(info_before)
        ws_before = _world_state_dict(info_before, self.world_mem)
        ctx = {}
        if action in ("turn_in_quest", "return_to_giver", "accept_quest"):
            for q in (info_before.get("quests", {}).get("active") or []):
                if q.get("state") in ("active", "ready", "complete"):
                    ctx["quest"] = q
                    break
            if action == "accept_quest":
                for e in (info_before.get("nearby") or []):
                    if (e.get("kind") == "npc" or e.get("type") == "npc") and (e.get("questIds") or e.get("questId")):
                        ctx["npc"] = e
                        break
        after, verdict, outcome_kind = self._run_skill(action, ctx, info_before)
        ws_after = _world_state_dict(after, self.world_mem)
        reward = outcome_reward(ws_before, ws_after, verdict, outcome_kind)
        if learn and outcome_kind != "ENV_ERROR":
            self.policy.learn(ws_before, action, reward, next_state=ws_after, outcome_kind=outcome_kind)
        return {"action": action, "verdict": verdict, "outcome_kind": outcome_kind,
                "reward": reward, "ws_before": ws_before, "ws_after": ws_after}

    def step_no_learn(self, exploration_weight: float = 0.0) -> dict:
        """One cycle with memory FROZEN — used for honest BEFORE/AFTER measurement.

        Identical decision path and identical reward computation as step(); the
        only difference is that nothing is written to memory. Without this, the
        act of measuring a policy would also train it, and BEFORE/AFTER would not
        be comparable.

        `exploration_weight=0.0` by default at measurement: the count-based
        exploration bonus is disabled, so the measured P(action) reflects Q ONLY —
        this removes the exploration/visit-count confound (user review 2026-08-17,
        point #6) when comparing BEFORE vs AFTER choice probabilities.
        """
        return self._cycle(learn=False, exploration_weight=exploration_weight)

    def _cycle(self, learn: bool = True, exploration_weight: float = 1.0) -> dict:
        # 0. Survival / recovery state machine. A dead character cannot act.
        # respawn() releases the spirit + resurrects at the healer; the bridge now
        # returns the REAL `revived` flag (dead:false AND hp>0), so we STOP spinning
        # on a corpse instead of trusting a blind ok:true. If resurrection fails N
        # times in a row, we PAUSE this cycle as ENV_ERROR (no farming/heal/loot, no
        # RL transition recorded) and let the launcher reconnect — exactly the
        # "RESPAWN_FAILED -> ENV_ERROR/PAUSE" branch from the design. We do NOT raise:
        # a failed respawn is an infra/recovery condition, not a programming bug, and
        # must not poison the policy with a false lesson.
        if self.env._last_info.get("player", {}).get("dead"):
            info, alive = self.env.respawn()
            tries = 1
            while not alive and tries < self.RESPAWN_MAX_ATTEMPTS:
                time.sleep(2.0)
                info, alive = self.env.respawn()
                tries += 1
            if not alive:
                # RESPAWN_FAILED: pause without emitting a normal RL transition.
                sys.stderr.write(
                    "[agent] respawn failed %d times; pausing cycle as ENV_ERROR\n" % tries)
                return {
                    "action": "recover", "verdict": "FAILURE", "outcome_kind": "ENV_ERROR",
                    "reward": 0.0,
                    "ws_before": _world_state_dict(info, self.world_mem), "ws_after": _world_state_dict(info, self.world_mem),
                }
        info_before = self.env._last_info
        self._remember_visible_world(info_before)
        ws_before = _world_state_dict(info_before, self.world_mem)

        # 0b. GoalFSM sync: drive the explicit current_goal from OBSERVED facts
        # each step. update_from_world() only sets the phase; it does not pick a
        # skill. Death is handled by the respawn-glue below (enter_dead /
        # resume_after_respawn), which preserves pre_death_goal.
        # 2026-08-24: ЗДЕСЬ БЫЛ ТРЕТИЙ ПИСАТЕЛЬ ЦЕЛИ.
        # play_autonomous уже вызывает update_from_world ДО консультации мозга
        # (строка 327), поэтому повторный вызов внутри step() только затирал
        # решение, принятое между ними, — измерено: все квестовые цели LLM
        # умирали через 6 строк, goal_switches = 0.71/шаг, quests_turned_in = 0
        # за 3000 шагов. Синхронизация фазы с миром осталась ровно в одном
        # месте (play_autonomous), здесь мы только ЧИТАЕМ цель.
        if self.fsm is not None and getattr(self, "sync_fsm_in_step", False):
            # аварийный тумблер: включать только если раннер НЕ синхронизирует FSM
            try:
                self.fsm.update_from_world(ws_before)
            except Exception:
                traceback.print_exc()

        # 1. Policy decides (learned + exploration), CONSTRAINED to the current
        # FSM phase. This stops the flat softmax from choosing a global action
        # (e.g. explore) when the agent should be returning the quest.
        # Pass ws_before explicitly so decide() and learn() use the IDENTICAL
        # WorldState -> identical bucket key (see world_state.py for the bug this
        # prevents).
        fsm_goal = self.fsm.goal if self.fsm is not None else None
        # step_idx нужен политике для разведочного бюджета gather-гейта
        # (GATHER_PROBE_EVERY): раз в N шагов пробуем действие вопреки фильтру.
        self._step_counter = getattr(self, "_step_counter", 0) + 1
        try:
            self.policy.step_idx = self._step_counter
        except Exception:
            pass
        # Explicit decision context from Autonomy (replaces hidden hints channel)
        _ctx = getattr(self.policy, "_ctx", None)
        _decide_kwargs = {}
        if _ctx is not None:
            _decide_kwargs["context"] = _ctx
        action, ctx = self.policy.decide(info_before, ws=ws_before,
                                          exploration_weight=exploration_weight,
                                          goal=fsm_goal, **_decide_kwargs)

        # 2-5. Skill -> Capability -> Game -> WorldState(after) -> Verifier
        after, verdict, outcome_kind = self._run_skill(action, ctx, info_before)
        _trace("SKILL_DONE action=%s" % (action,))

        # Persist newly observed vendors/NPC facts after every real transition.
        self._remember_visible_world(after)
        _trace("REMEMBER_DONE")

        # 6. Reward from FACT (reward.py), not from our opinion
        ws_after = _world_state_dict(after, self.world_mem)
        reward = outcome_reward(ws_before, ws_after, verdict, outcome_kind)
        _trace("REWARD_DONE r=%.2f" % (reward,))

        # 7. Memory learns — UNLESS infra error (ENV_ERROR -> no false lesson)
        #    or measurement mode (learn=False).
        if learn and outcome_kind != "ENV_ERROR":
            # candidate set of the NEXT state, so the TD bootstrap maxes only over
            # reachable actions (not over globally-unreachable ones).
            next_cands = self.policy._candidates(after, ws_after,
                                                 goal=fsm_goal)
            self.policy.learn(ws_before, action, reward, next_state=ws_after,
                              outcome_kind=outcome_kind, candidates=next_cands)
            # 7b. ReplayBuffer + StrategyMemory are fed by play_autonomous.py
            # (which has the full per-step world view and classifies rare events
            # there). Do NOT double-push here — that would store incompatible
            # bucket-string transitions alongside its dict transitions and break
            # train_from_replay(). See play_autonomous.py ~line 562.
        _trace("MEMORY_DONE")

        return {
            "action": action,
            "verdict": verdict,
            "outcome_kind": outcome_kind,
            "reward": reward,
            "ws_before": ws_before,
            "ws_after": ws_after,
        }

    def run(self, n_steps: int = 200, accept_welcome: bool = True, save_every: int = 50):
        """Run n learning-cycle steps. Optionally accept the welcome quest first
        (so there is an objective to learn against).

        Autonomous mode: loops until n_steps done or ENV_ERROR. Saves memory
        every `save_every` steps so a killed/restarted process resumes learning
        from the persisted ExperienceStore (no lesson lost). On exit, stops the
        player's movement so the character does not keep spinning (the bridge
        holds controller input until a stop() arrives)."""
        if accept_welcome:
            self._maybe_accept_welcome()
        for i in range(n_steps):
            try:
                rec = self.step()
            except BrowserBridgeError as ex:
                # Infra failure (bridge/CDP down, transport rejected). This is
                # NOT a game lesson: record ENV_ERROR, do NOT learn, wait for
                # recovery. Distinct from a programming bug below.
                rec = {"action": "?", "verdict": "ERROR", "outcome_kind": "ENV_ERROR",
                       "reward": 0.0, "error": str(ex)}
                traceback.print_exc()
            except Exception as ex:
                # Programming error (NameError/KeyError/TypeError/AttributeError
                # in policy/skill/reward/world_state). This is a REAL BUG — crash
                # loudly so it cannot hide behind ENV_ERROR and silently poison
                # 10h of self-play. Do NOT mask as ENV_ERROR, do NOT continue.
                traceback.print_exc()
                raise
            if i % 10 == 0 or rec["outcome_kind"] == "ENV_ERROR":
                wb = rec.get("ws_before") or {}
                wa = rec.get("ws_after") or {}
                print(f"[{i}] {rec['action']:14s} v={rec['verdict']:12s} "
                      f"kind={rec['outcome_kind']:12s} r={rec['reward']:+.2f} "
                      f"hp={wb.get('hp_frac', 0):.2f} "
                      f"qprog={wa.get('quest_progress')} "
                      f"dist={wa.get('distance_to_giver', 0):.0f}")
            if rec["outcome_kind"] == "ENV_ERROR":
                # Infra failure (bridge/CDP down), NOT a game lesson. Instead of
                # stopping, wait for the bridge to come back and keep playing so the
                # agent is truly autonomous (survives transient bridge restarts).
                print(f"  >> ENV_ERROR at step {i} — bridge down, waiting for recovery (no lesson)")
                waited = 0
                while waited < 1800:  # up to 30 min
                    time.sleep(10)
                    waited += 10
                    try:
                        if (self.env._last_info or {}).get("player") is not None:
                            print(f"  >> bridge recovered after {waited}s, resuming")
                            break
                    except Exception:
                        pass
                else:
                    print("  >> bridge not recovered in 30m — giving up")
                    break
            if save_every and (i + 1) % save_every == 0:
                self.mem.save()
        # persist + report what was learned
        self.mem.save()
        # stop residual movement (bridge holds controller input otherwise)
        try:
            if hasattr(self.env, "base") and hasattr(self.env.base, "stop"):
                self.env.base.stop()
        except Exception:
            pass
        try:
            if hasattr(self.env, "_post"):
                self.env._post({"action": "raw_move", "kind": "stop"})
        except Exception:
            pass
        return self.mem.snapshot()

    def _maybe_accept_welcome(self):
        """Accept the nearest available quest IF none is active yet.

        Online interface: accept_quest is high-level skill index 2 (SKILLS order
        in hierarchical_env), issued via env.step(2) — BrowserBase has no
        accept_quest method. We navigate to the giver, then step(idx=2)."""
        active = (self.env._last_info or {}).get("quests", {}).get("active") or []
        if active:
            return
        giver = None
        for _ in range(24):
            near = self.env._last_info.get("nearby") or []
            g = [e for e in near if e.get("kind") == "npc" and (e.get("questIds") or e.get("questId"))]
            if g:
                giver = g[0]; break
            # turn a bit to scan for the giver
            self.env.base.step(ACT_TURN_LEFT)
            near = self.env._last_info.get("nearby") or []
        if giver:
            qid = (giver.get("questIds") or [None])[0]
            self.env._navigate_to_coord(giver.get("x"), giver.get("z"), max_steps=80)
            # pass the giver ctx so env.step(2) issues acceptQuest(questId),
            # not a bare interact (the online bridge requires the questId).
            self.env.step(2, {"npc": giver, "questId": qid})
            # Persist the turn-in NPC (accept_quest surfaced it via env.last_giver).
            lg = getattr(self.env, "last_giver", None)
            if lg and lg.get("questId"):
                self.world_mem.remember_giver(str(lg["questId"]), str(lg.get("giverId")),
                                              lg.get("giverPos") or {})
                self.world_mem.save()
            self.env._last_info = self.env._last_info


if __name__ == "__main__":
    # Long autonomous self-play: the agent balances the FULL skill set
    # (quest/loot/sell/farm/heal/buy/equip/explore) via its learned policy,
    # not a scripted bot. 3000 steps ~ enough to walk out of the start zone,
    # reach mobs + trade-vendors, and exercise buy/heal/equip for real.
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
    obs, info = env.reset(seed=42)
    mem = ExperienceStore()
    agent = Agent(env, mem, seed=12345)
    # В standalone-режиме раннера play_autonomous нет, значит НИКТО не
    # синхронизирует FSM с миром — включаем тумблер, чтобы фаза не замерла.
    # В обычном режиме (play_autonomous) он ВЫКЛЮЧЕН: там синхронизация одна,
    # в раннере, и второй вызов затирал бы решения (см. комментарий в _cycle).
    agent.sync_fsm_in_step = True
    learned = agent.run(n_steps=3000, save_every=100)
    print("\n=== Learned value snapshot (state_bucket -> {action: value}) ===")
    for bucket, acts in learned.items():
        print(bucket)
        for a, v in sorted(acts.items(), key=lambda kv: -kv[1]):
            print(f"    {a:14s} {v:+.3f}")
    env.close()

def resolve_giver_pos(quest_id, giver_id, nearby, quest_giver, world_mem,
                      json_givers, player_pos, game_source=None,
                      turnInNpc_coords=None):
    """Resolve giver (x, z) for accept_quest navigation.

    Order (game truth wins over runtime memory that can drift/stale):
      0. turnInNpc_coords — if active quest already has turnInNpc x/z, use that
         directly. This avoids stale static JSON when policy has the full quest.
      1. live snapshot: info.nearby by giver_id
      2. live snapshot: nearest quest-NPC in nearby
      2.5. GameSource (dynamic, from window.__game.sim.worldContent.npcs)
      3. fsm.quest_giver x/z
      4. STATIC game table (giver_positions.json) — DEPRECATED
      5. world_mem.quest_givers - LAST
    Returns (x, z) or None.
    """
    # Priority 0: active quest turnInNpc — authoritative, never stale.
    if turnInNpc_coords and turnInNpc_coords[0] is not None:
        return turnInNpc_coords

    gpos = None
    if giver_id is not None:
        for e in nearby:
            if str(e.get("id")) == str(giver_id):
                gpos = (e.get("x"), e.get("z"))
                break
    if gpos is None:
        qnpcs = [e for e in nearby
                 if isinstance(e, dict)
                 and (e.get("questIds") or e.get("questId") or e.get("questGiver"))]
        qnpcs.sort(key=lambda n: n.get("dist", float("inf")))
        if qnpcs:
            gn = qnpcs[0]
            gpos = (gn.get("x"), gn.get("z"))
    # Dynamic game truth: GameSource reads window.__game.sim.worldContent.npcs
    # which has 91 NPCs with questIds — this is where offline NPC positions live,
    # since offline does NOT spawn NPCs into sim.entities (info.nearby is empty
    # for NPCs offline). Use it before falling back to stale static JSON.
    if gpos is None and game_source is not None and quest_id:
        try:
            _gs_pos = game_source.get_giver_pos_for_quest(quest_id)
            if _gs_pos is not None:
                gpos = _gs_pos
        except Exception:
            pass  # best-effort; fall through to stale fallbacks
    if gpos is None and isinstance(quest_giver, dict) and quest_giver.get("x") is not None:
        gpos = (quest_giver.get("x"), quest_giver.get("z"))
    if gpos is None and json_givers:
        # DEPRECATED — static duplicate, kept only until GameSource proven stable.
        # Exact match by giver_id first (policy named a specific NPC).
        if giver_id is not None and str(giver_id) in json_givers:
            _gd = json_givers[str(giver_id)]
            gpos = (_gd.get("x"), _gd.get("z"))
        else:
            best = None
            best_d = float("inf")
            px, pz = (player_pos or [0, 0])[0], (player_pos or [0, 0])[1]
            for gid, gd in json_givers.items():
                d = (gd.get("x", 0) - px) ** 2 + (gd.get("z", 0) - pz) ** 2
                if d < best_d:
                    best_d = d
                    best = gd
            if best is not None:
                gpos = (best.get("x"), best.get("z"))
    if gpos is None and world_mem:
        gm = getattr(world_mem, "quest_givers", None) or {}
        for gd in gm.values():
            gp = gd.get("giver_pos") or {}
            if gp.get("x") is not None:
                gpos = (gp.get("x"), gp.get("z"))
                break
    return gpos
