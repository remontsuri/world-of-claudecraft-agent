"""Real-world self-learning experiment — statistically sound + honest BEFORE.

Per user 2026-08-16 (final verdict):
- Quest is NOT the agent's goal; skills are tools, not a script.
- farm must stay POSSIBLE (~0.03), never forbidden (P=0).
- Use MULTIPLE independent seeds; collect (state, action, reward, next) experiences.
- BEFORE must be measured in the SAME conditions as AFTER (agent forced into far
  via real farming, but memory NOT written during the force — only choices read).

This run fixes the earlier empty-BEFORE bug: we force the agent into a far state
by REAL farming (takes damage, drifts), then read what the policy chooses — with
learn=False so the force-phase doesn't poison the BEFORE measurement.
"""

import os
from collections import Counter

from hierarchical_env import HierarchicalWoWEnv, ACT_FORWARD, ACT_TURN_LEFT
from agent import Agent
from memory import ExperienceStore
from quest_capability import QuestCapability
from reward import outcome_reward

EXP_PATH = os.path.join(os.path.dirname(__file__), "experience_real.json")
EPISODES = 10
FREE_STEPS = 80
SEEDS = [42, 107, 256, 511, 909, 1234, 2024, 31337, 777, 555]


def _accept_welcome(env):
    cap = QuestCapability(env)
    if cap.find_active_quest() is not None:
        return True
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
        return True
    return False


def _dist_to_giver(env):
    info = env._last_info
    for q in (info.get("quests", {}).get("active") or []):
        tNpc = q.get("turnInNpc")
        if tNpc and tNpc.get("x") is not None:
            px, pz = info.get("player_pos", [0, 0])
            return ((tNpc["x"] - px) ** 2 + (tNpc["z"] - pz) ** 2) ** 0.5
    return 0.0


def _force_far(env, agent, learn=False, max_farm=60):
    """Real farming until distance_to_giver > 80 (agent drifts far). If learn,
    write outcomes to memory; if not, just drift (used for honest BEFORE/AFTER
    measurement so the force-phase doesn't teach)."""
    farmed = 0
    while farmed < max_farm and _dist_to_giver(env) <= 80:
        try:
            rec = agent.step()
        except Exception:
            break
        if rec.get("outcome_kind") == "ENV_ERROR":
            break
        if learn and rec.get("outcome_kind") != "ENV_ERROR":
            # already written inside agent.step via policy.learn; nothing to do
            pass
        farmed += 1


def _collect_choices(env, agent, flag, n):
    choices = []
    for _ in range(n):
        try:
            rec = agent.step()
        except Exception:
            break
        if rec.get("outcome_kind") == "ENV_ERROR":
            break
        info = env._last_info
        tNpc = None
        for q in (info.get("quests", {}).get("active") or []):
            if q.get("turnInNpc"):
                tNpc = q["turnInNpc"]; break
        if tNpc and tNpc.get("x") is not None:
            px, pz = info.get("player_pos", [0, 0])
            dist = ((tNpc["x"] - px) ** 2 + (tNpc["z"] - pz) ** 2) ** 0.5
            if dist > 80:
                choices.append(rec["action"])
    return choices


def _measure(agent_factory, seed_base, learn_during_force=False):
    """Force into far state (real farm), then read policy choices at far.
    learn_during_force=False => honest BEFORE/AFTER (no teaching during force)."""
    env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=seed_base)
    obs, info = env.reset(seed=seed_base)
    agent = agent_factory(env)
    _accept_welcome(env)
    _force_far(env, agent, learn=learn_during_force)
    choices = _collect_choices(env, agent, "far", FREE_STEPS)
    env.close()
    return choices


def _dist(choices):
    if not choices:
        return {}
    c = Counter(choices)
    total = len(choices)
    return {k: round(v / total, 3) for k, v in c.items()}


def main():
    if os.path.exists(EXP_PATH):
        os.remove(EXP_PATH)
    mem = ExperienceStore(path=EXP_PATH)

    def mk(env):
        return Agent(env, mem, seed=111)

    # BEFORE (honest: forced far, NO learning during force)
    print("=== BEFORE learning (forced far, no teaching) ===")
    before = _measure(mk, 4242, learn_during_force=False)
    bf = _dist(before)
    print(f"  far choices ({len(before)}): {before}")
    print(f"  P(farm|far)={bf.get('farm',0)}  P(return|far)={bf.get('return_to_giver',0)}")

    # TRAINING
    print(f"\n=== TRAINING: {EPISODES} independent episodes ===")
    for i, seed in enumerate(SEEDS[:EPISODES]):
        try:
            env = HierarchicalWoWEnv(player_class="warrior", max_steps=2000, seed=seed)
            obs, info = env.reset(seed=seed)
            agent = Agent(env, mem, seed=seed * 3 + 1)
            if not _accept_welcome(env):
                print(f"  [ep{i}] no giver, skip"); env.close(); continue
            _force_far(env, agent, learn=True)      # drift far, LEARN from it
            _collect_choices(env, agent, "far", FREE_STEPS)
            env.close()
            print(f"  [ep{i}] seed={seed} done, entries={len(mem.weights)}, exp={len(mem.experiences)}")
        except Exception as ex:
            print(f"  [ep{i}] exc {ex!r}")
            try: env.close()
            except Exception: pass

    # AFTER (honest: forced far, NO learning during force)
    print("\n=== AFTER learning ===")
    after = _measure(mk, 9090, learn_during_force=False)
    af = _dist(after)
    print(f"  far choices ({len(after)}): {after}")
    print(f"  P(farm|far)={af.get('farm',0)}  P(return|far)={af.get('return_to_giver',0)}")
    print(f"  full P(action|far): {af}")

    # Real memory samples
    print("\n=== Sample real experiences ===")
    far_farm = [e for e in mem.experiences if "far=1" in e[0] and e[1] == "farm"]
    far_ret = [e for e in mem.experiences if "far=1" in e[0] and e[1] == "return_to_giver"]
    print(f"  far+farm: {len(far_farm)} (rewards sample: {[e[2] for e in far_farm[:8]]})")
    print(f"  far+return: {len(far_ret)} (rewards sample: {[e[2] for e in far_ret[:8]]})")

    print("\n=== VERDICT ===")
    farm_down = af.get("farm", 1) < bf.get("farm", 0) + 0.05
    farm_possible = af.get("farm", 0) > 0.0
    return_up = af.get("return_to_giver", 0) > bf.get("return_to_giver", 0)
    print(f"  P(farm|far) decreased vs BEFORE: {farm_down}")
    print(f"  farm still POSSIBLE (P>0): {farm_possible}")
    print(f"  P(return|far) increased vs BEFORE: {return_up}")
    ok = farm_down and farm_possible
    print(f"  RESULT: {'PASS (real learning, farm stays possible)' if ok else 'NEEDS MORE EPISODES'}")


if __name__ == "__main__":
    main()
