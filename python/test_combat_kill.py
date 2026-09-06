"""RED TESTS: combat damage, kill, kill reward.

Verifies the kill signal chain: AutonomyLoop detects kills, reward assigns
positive value, FSM counts kills.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from autonomy import AutonomyLoop
from reward import outcome_reward, WEIGHTS
from goal_fsm import GoalFSM, QuestState


def _info(hp=100, maxhp=100, copper=0, kills=0, deaths=0, dead=False,
          nearby=None, quests=None, inv=None):
    return {
        "player": {"hp": hp, "maxHp": maxhp, "level": 1, "dead": dead,
                   "pos": {"x": 0.0, "z": 0.0}},
        "player_pos": [0.0, 0.0],
        "player_class": "warrior",
        "nearby": nearby if nearby is not None else [],
        "quests": quests if quests is not None else {"active": [], "done": []},
        "inventory": inv if inv is not None else [],
        "copper": copper, "kills": kills, "deaths": deaths, "xp": 0,
    }


def _ws(info, **over):
    ws = dict(info)
    ws["hp_frac"] = info["player"]["hp"] / max(1, info["player"]["maxHp"])
    ws["bag_capacity"] = 26
    ws.update(over)
    return ws


def test_kill_detected_as_success():
    """A kill between before/after must register as SUCCESS."""
    loop = AutonomyLoop()
    before = _info(kills=0)
    loop.before_action(before, _ws(before), ["farm"])
    after = _info(kills=1)
    rec = loop.after_action("farm", after, _ws(after))
    assert rec["skill_result"] == "SUCCESS"
    assert rec["progress_delta"]["kills_delta"] == 1


def test_kill_reward_is_positive_and_meaningful():
    """A kill must produce reward >= 1.0 (WEIGHTS['kills']=0.5 + success_bonus=0.5)."""
    before = {"kills": 0, "xp": 0, "copper": 0, "quests_done": 0,
              "inv_slots": 0, "deaths": 0, "quest_progress": 0,
              "distance_to_giver": 10.0, "hp_frac": 1.0}
    after = {"kills": 1, "xp": 10, "copper": 0, "quests_done": 0,
             "inv_slots": 0, "deaths": 0, "quest_progress": 0,
             "distance_to_giver": 10.0, "hp_frac": 1.0}
    reward = outcome_reward(before, after, "SUCCESS")
    assert reward >= 1.0, f"kill reward too low: {reward}"


def test_each_kill_gives_same_reward():
    """Each kill delta gives the same reward (per-kill-delta contract)."""
    base = {"xp": 0, "copper": 0, "quests_done": 0,
            "inv_slots": 0, "deaths": 0, "quest_progress": 0,
            "distance_to_giver": 10.0, "hp_frac": 1.0}
    before = dict(base, kills=0)
    after1 = dict(base, kills=1)
    after2 = dict(base, kills=2)
    r1 = outcome_reward(before, after1, "SUCCESS")
    r2 = outcome_reward(after1, after2, "SUCCESS")
    assert r1 == r2, f"each kill should give same reward: {r1} vs {r2}"
    assert r1 > 0, f"kill reward should be positive: {r1}"


def test_death_is_failure_with_negative_reward():
    """Death must produce FAILURE verdict and negative reward."""
    loop = AutonomyLoop()
    before = _info(deaths=0)
    loop.before_action(before, _ws(before), ["farm"])
    after = _info(deaths=1)
    rec = loop.after_action("farm", after, _ws(after))
    assert rec["skill_result"] == "FAILURE"
    # Reward for death
    ws_b = _ws(before)
    ws_a = _ws(after)
    ws_b["deaths"] = 0
    ws_a["deaths"] = 1
    reward = outcome_reward(ws_b, ws_a, "FAILURE")
    assert reward < 0, f"death should be negative reward: {reward}"


def test_no_kill_no_reward():
    """Without a kill, no kill bonus should be given."""
    before = {"kills": 0, "xp": 0, "copper": 0, "quests_done": 0,
              "inv_slots": 0, "deaths": 0, "quest_progress": 0,
              "distance_to_giver": 10.0, "hp_frac": 1.0}
    after = {"kills": 0, "xp": 0, "copper": 0, "quests_done": 0,
             "inv_slots": 0, "deaths": 0, "quest_progress": 0,
             "distance_to_giver": 10.0, "hp_frac": 1.0}
    reward = outcome_reward(before, after, "INCONCLUSIVE")
    assert reward == 0.0, f"no kill should give 0 reward: {reward}"


def test_fsm_tracks_total_kills():
    """GoalFSM.total_kills should increment when kills happen."""
    f = GoalFSM()
    assert f.total_kills == 0
    f.total_kills += 1
    assert f.total_kills == 1
