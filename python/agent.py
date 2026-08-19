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
"""

import sys
import traceback

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT, SKILLS
from verifiers_py import verify_skill
from policy import GoalManager
from memory import ExperienceStore
from reward import outcome_reward
from world_state import build_world_state
import quest_skill
from quest_capability import QuestCapability

# Map skill name -> hierarchical_env action index
SKILL_INDEX = {name: i for i, name in enumerate(SKILLS)}


def _world_state_dict(info: dict) -> dict:
    """WorldState for reward + memory — delegates to the SINGLE shared builder.

    This used to build its own partial dict (no has_mob/has_corpse/has_junk/
    danger), while policy._world_state() omitted distance_to_giver/in_combat.
    Both were fed to memory._bucket(), so decide() read one key and learn()
    wrote another and no lesson was ever visible to the decision path
    (measured by _diag_bucket.py). One builder = one bucket key.
    """
    return build_world_state(info)


class Agent:
    def __init__(self, env: HierarchicalWoWEnv, memory: ExperienceStore, seed=None):
        self.env = env
        self.mem = memory
        self.policy = GoalManager(memory, temperature=1.2, seed=seed)
        self.cap = QuestCapability(env)

    def _run_skill(self, action: str, ctx: dict, info_before: dict) -> dict:
        """Execute one skill, return (after_info, verdict, outcome_kind)."""
        try:
            if action == "return_to_giver":
                # atomic: navigate back to the turn-in NPC (short nav, env-safe)
                res = quest_skill.return_to_giver(self.env, ctx)
                after = self.env._last_info
                verdict = "SUCCESS" if res == "SUCCESS" else "INCONCLUSIVE"
                return after, verdict, "OK"
            if action == "explore":
                # sustained walk toward nearest mob/NPC (or forward) so the agent
                # actually covers ground. BrowserEnv.explore_walk talks to the
                # online bridge; falls back to a raw forward step elsewhere.
                if hasattr(self.env, "explore_walk"):
                    self.env.explore_walk(steps=10)
                else:
                    self.env.base.step(ACT_FORWARD)
                after = self.env._last_info
                return after, "INCONCLUSIVE", "OK"
            if action == "turn_in_quest":
                # atomic: walk back (short nav) + turn_in. Use QuestCapability path
                # so we get the server-side turn-in + verifier-correct handle.
                res = quest_skill.turn_in_quest(self.env, ctx)
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
                idx = SKILL_INDEX.get(action)
                if idx is None:
                    return info_before, "FAILURE", "OK"
                before = info_before
                self.env.step(idx)
                after = self.env._last_info
                # verifier (objective truth)
                handle = None
                if action == "turn_in_quest" and ctx.get("quest"):
                    handle = str(ctx["quest"].get("id"))
                elif action == "accept_quest" and ctx.get("npc"):
                    qids = ctx["npc"].get("questIds") or ctx["npc"].get("questId") or [None]
                    handle = str(qids[0]) if qids else None
                v = verify_skill(action, {"before": before, "after": after, "handle": handle})
                verdict = v if isinstance(v, str) else str(v)
                return after, verdict, "OK"
        except Exception:
            # server crash / infra failure — treat as ENV_ERROR, NOT a game outcome
            return info_before, "FAILURE", "ENV_ERROR"

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
        ws_before = _world_state_dict(info_before)
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
        ws_after = _world_state_dict(after)
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
        # 0. Survival: a dead character cannot act. Respawn (release spirit +
        # resurrect at healer) so the loop keeps running instead of spinning
        # on a corpse. This is infra safety, NOT a learned action.
        if self.env._last_info.get("player", {}).get("dead"):
            self.env.respawn()
        info_before = self.env._last_info
        ws_before = _world_state_dict(info_before)

        # 1. Policy decides (learned + exploration).
        # Pass ws_before explicitly so decide() and learn() use the IDENTICAL
        # WorldState -> identical bucket key (see world_state.py for the bug this
        # prevents).
        action, ctx = self.policy.decide(info_before, ws=ws_before,
                                          exploration_weight=exploration_weight)

        # 2-5. Skill -> Capability -> Game -> WorldState(after) -> Verifier
        after, verdict, outcome_kind = self._run_skill(action, ctx, info_before)

        # 6. Reward from FACT (reward.py), not from our opinion
        ws_after = _world_state_dict(after)
        reward = outcome_reward(ws_before, ws_after, verdict, outcome_kind)

        # 7. Memory learns — UNLESS infra error (ENV_ERROR -> no false lesson)
        #    or measurement mode (learn=False).
        if learn and outcome_kind != "ENV_ERROR":
            self.policy.learn(ws_before, action, reward, next_state=ws_after, outcome_kind=outcome_kind)

        return {
            "action": action,
            "verdict": verdict,
            "outcome_kind": outcome_kind,
            "reward": reward,
            "ws_before": ws_before,
            "ws_after": ws_after,
        }

    def run(self, n_steps: int = 200, accept_welcome: bool = True):
        """Run n learning-cycle steps. Optionally accept the welcome quest first
        (so there is an objective to learn against)."""
        if accept_welcome:
            self._maybe_accept_welcome()
        for i in range(n_steps):
            try:
                rec = self.step()
            except Exception as ex:
                rec = {"action": "?", "verdict": "ERROR", "outcome_kind": "ENV_ERROR",
                       "reward": 0.0, "error": str(ex)}
                traceback.print_exc()
            if i % 10 == 0 or rec["outcome_kind"] == "ENV_ERROR":
                print(f"[{i}] {rec['action']:14s} v={rec['verdict']:12s} "
                      f"kind={rec['outcome_kind']:12s} r={rec['reward']:+.2f} "
                      f"hp={rec['ws_before']['hp_frac']:.2f} "
                      f"qprog={rec['ws_after']['quest_progress']} "
                      f"dist={rec['ws_after']['distance_to_giver']:.0f}")
            if rec["outcome_kind"] == "ENV_ERROR":
                print(f"  >> ENV_ERROR at step {i} — stopping (infra failure, not a lesson)")
                break
        # persist + report what was learned
        self.mem.save()
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
            self.env.step(2)  # accept_quest skill index
            self.env._last_info = self.env._last_info


if __name__ == "__main__":
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=5000, seed=42)
    obs, info = env.reset(seed=42)
    mem = ExperienceStore()
    agent = Agent(env, mem, seed=12345)
    learned = agent.run(n_steps=200)
    print("\n=== Learned value snapshot (state_bucket -> {action: value}) ===")
    for bucket, acts in learned.items():
        print(bucket)
        for a, v in sorted(acts.items(), key=lambda kv: -kv[1]):
            print(f"    {a:14s} {v:+.3f}")
    env.close()
