"""Failing tests for the three policy bugs (systematic-debugging Phase 4).

Run: PYTHONPATH=. python _test_policy_bugs.py
All three must FAIL before the fix, then PASS after.
"""
import os, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from world_state import build_world_state
from policy import GoalManager
from memory import ExperienceStore

EXP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experience_autonomous.json")
HERE = os.path.dirname(os.path.abspath(__file__))


def _snapshot():
    data = json.dumps({"action": "snapshot"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8791/", data=data,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=10))


def test_strong_mob_excluded_from_farm():
    """Bug 1: agent dies on strong mobs because FARM is offered on ANY mob.
    Fix: FARM candidate only when a WEAK mob (maxHp <= player.maxHp*1.3) is near.
    """
    # synthetic info: player weak, one strong mob nearby
    info = {
        "player": {"hp": 93, "maxHp": 93, "level": 4, "dead": False},
        "nearby": [{"kind": "mob", "type": "mob", "maxHp": 179, "hp": 179,
                     "x": 1, "z": 1, "lootable": False}],
        "quests": {"active": [], "ready": [], "done": []},
        "inventory": [], "player_pos": [0, 0],
    }
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore(path=EXP_PATH), seed=1)
    cands = gm._candidates(info, ws)
    assert "farm" not in cands, f"FARM offered on strong mob! candidates={cands}"
    print("PASS test_strong_mob_excluded_from_farm")


def test_weak_mob_allows_farm():
    """Sanity: weak mob nearby -> FARM IS a candidate."""
    info = {
        "player": {"hp": 93, "maxHp": 93, "level": 4, "dead": False},
        "nearby": [{"kind": "mob", "type": "mob", "maxHp": 50, "hp": 50,
                     "x": 1, "z": 1, "lootable": False}],
        "quests": {"active": [], "ready": [], "done": []},
        "inventory": [], "player_pos": [0, 0],
    }
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore(path=EXP_PATH), seed=1)
    cands = gm._candidates(info, ws)
    assert "farm" in cands, f"FARM missing on weak mob! candidates={cands}"
    print("PASS test_weak_mob_allows_farm")


def test_accept_quest_ctx_has_correct_questid():
    """Bug 3: the questId sent to the bridge for accept_quest must be the NPC's
    OWN questId, never the first active quest (different NPC -> 'unavailable').
    Tests BOTH layers: (a) policy.decide sets ctx['questId'] from the NPC, and
    (b) browser_env.step prioritises ctx['questId'] over ctx['quest']['id'].
    Reproducible: first active quest deliberately belongs to a different NPC.
    We sample decide() over many seeds until it picks accept_quest, then inspect
    the ctx it produced for that action."""
    npc = {"kind": "npc", "id": 12, "name": "Darva",
           "questIds": ["q_prof_attune_smith", "q_prof_amends_smith"]}
    first_active = {"id": "q_wolves", "state": "active", "objectives": []}  # Redbrook's quest
    info = {
        "player": {"hp": 93, "maxHp": 93, "level": 4, "dead": False},
        "nearby": [npc],
        "quests": {"active": [first_active], "ready": [], "done": []},
        "inventory": [], "player_pos": [0, 0],
    }
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore(path=EXP_PATH), seed=1)

    # sample decide() over many seeds to catch the accept_quest branch
    sampled_ctx = None
    for s in range(200):
        gm = GoalManager(ExperienceStore(path=EXP_PATH), seed=s)
        action, ctx = gm.decide(info, ws=ws, exploration_weight=1.0)
        if action == "accept_quest":
            sampled_ctx = ctx
            break
    assert sampled_ctx is not None, "decide never selected accept_quest in 200 seeds"
    ctx = sampled_ctx
    assert "questId" in ctx, "decide did not set ctx['questId'] for accept_quest"
    assert ctx["questId"] in npc["questIds"], (
        f"decide sent questId={ctx['questId']!r}, npc quests={npc['questIds']!r}")

    # (b) browser_env.step must prioritise ctx['questId'] over ctx['quest']['id']
    q = ctx.get("quest") or {}
    buggy_qid = q.get("id") or ctx.get("questId")        # OLD (buggy) precedence
    fixed_qid = ctx.get("questId") or q.get("id")        # NEW (fixed) precedence
    assert buggy_qid == first_active["id"], "sanity: old precedence picks first active quest"
    assert buggy_qid != npc["questIds"][0], (
        f"old precedence would send {buggy_qid!r} to npc {npc['questIds']!r} -> 'unavailable'")
    assert fixed_qid == npc["questIds"][0], (
        f"fixed precedence must send npc questId {npc['questIds'][0]!r}, got {fixed_qid!r}")
    print("PASS test_accept_quest_ctx_has_correct_questid")


def test_explore_suppressed_with_active_quest():
    """Bug 2: with an active quest and a quest NPC nearby, explore must NOT be a
    candidate (agent must progress the quest, not drift to fences)."""
    npc = {"kind": "npc", "id": 12, "name": "Darva", "questIds": ["q_x"]}
    info = {
        "player": {"hp": 93, "maxHp": 93, "level": 4, "dead": False},
        "nearby": [npc],
        "quests": {"active": [{"id": "q_x", "state": "active", "objectives": []}],
                   "ready": [], "done": []},
        "inventory": [], "player_pos": [0, 0],
    }
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore(path=EXP_PATH), seed=1)
    cands = gm._candidates(info, ws)
    assert "return_to_giver" in cands, f"return_to_giver missing! cands={cands}"
    assert "explore" not in cands, f"explore offered with active quest (drift)! cands={cands}"
    print("PASS test_explore_suppressed_with_active_quest")


def test_turn_in_uses_ready_quest():
    """Bug 3-bis: turn_in_quest must operate on a READY quest (objectives done),
    not the first active quest. decide() must set ctx['quest'] to a ready quest
    when action is turn_in, and surface its questId/npcId."""
    ready_q = {"id": "q_prowlers", "state": "ready",
               "objectives": [{"current": 5, "required": 5}],
               "turnInNpc": {"id": 16, "x": 4, "z": 285}}
    active_q = {"id": "q_wolves", "state": "active", "objectives": [{"current": 0, "required": 5}]}
    info = {
        "player": {"hp": 93, "maxHp": 93, "level": 4, "dead": False},
        "nearby": [],
        "quests": {"active": [active_q], "ready": [ready_q], "done": []},
        "inventory": [], "player_pos": [0, 0],
    }
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore(path=EXP_PATH), seed=1)
    # sample decide over seeds to land on turn_in_quest
    sampled = None
    for s in range(300):
        g = GoalManager(ExperienceStore(path=EXP_PATH), seed=s)
        action, ctx = g.decide(info, ws=ws, exploration_weight=1.0)
        if action == "turn_in_quest":
            sampled = (action, ctx)
            break
    assert sampled is not None, "decide never selected turn_in_quest in 300 seeds"
    _, ctx = sampled
    assert "quest" in ctx, "turn_in ctx missing quest"
    assert ctx["quest"]["id"] == "q_prowlers", (
        f"turn_in must use READY quest, got {ctx['quest'].get('id')!r}")
    assert ctx.get("questId") == "q_prowlers", f"turn_in questId wrong: {ctx.get('questId')!r}"
    assert ctx.get("npcId") == "16", f"turn_in npcId wrong: {ctx.get('npcId')!r}"
    print("PASS test_turn_in_uses_ready_quest")


def test_explore_allowed_when_no_quest():
    """Sanity: explore IS available when no quest active and no quest NPC near
    (early free-roam / discovery)."""
    info = {
        "player": {"hp": 93, "maxHp": 93, "level": 4, "dead": False},
        "nearby": [],
        "quests": {"active": [], "ready": [], "done": []},
        "inventory": [], "player_pos": [0, 0],
    }
    ws = build_world_state(info)
    gm = GoalManager(ExperienceStore(path=EXP_PATH), seed=1)
    cands = gm._candidates(info, ws)
    assert "explore" in cands, f"explore missing when no quest! cands={cands}"
    print("PASS test_explore_allowed_when_no_quest")


if __name__ == "__main__":
    fails = 0
    for t in [test_strong_mob_excluded_from_farm, test_weak_mob_allows_farm,
              test_accept_quest_ctx_has_correct_questid,
              test_turn_in_uses_ready_quest,
              test_explore_suppressed_with_active_quest,
              test_explore_allowed_when_no_quest]:
        try:
            t()
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            fails += 1
        except Exception as e:
            print(f"ERROR {t.__name__}: {e}")
            fails += 1
    print(f"\n{fails} test(s) failed" if fails else "\nALL TESTS PASS")
    sys.exit(1 if fails else 0)
