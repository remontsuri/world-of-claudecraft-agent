"""Тесты замкнутого автономного контура (ARCHITECTURE.md §13).

Запуск: cd python && python -m pytest test_autonomy_loop.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from autonomy import AutonomyLoop, RECOVERY_TO_SKILL


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
    """Минимальный ws: контур толерантен, ему хватает info + пары полей."""
    ws = dict(info)
    ws["hp_frac"] = info["player"]["hp"] / max(1, info["player"]["maxHp"])
    ws["bag_capacity"] = 26
    ws.update(over)
    return ws


# ----------------------------------------------------------- before_action

def test_before_action_returns_contract_shape():
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["farm", "buy", "gather"])
    for k in ("candidates", "subgoal", "forced_skill", "obs", "blocked"):
        assert k in out, k


def test_impossible_candidates_are_masked_out():
    loop = AutonomyLoop()
    info = _info()          # нет вендора, нет узлов
    out = loop.before_action(info, _ws(info), ["buy", "gather"])
    assert "buy" not in out["candidates"]
    assert "gather" not in out["candidates"]
    assert loop.stats["masked_out"] == 2


def test_candidates_never_empty():
    loop = AutonomyLoop()
    info = _info()
    out = loop.before_action(info, _ws(info), ["buy"])
    assert out["candidates"]          # explore fallback


def test_farm_survives_mask_when_mob_present():
    loop = AutonomyLoop()
    info = _info(nearby=[{"kind": "mob", "hp": 10, "level": 1, "dist": 6.0}])
    out = loop.before_action(info, _ws(info), ["farm", "buy"])
    assert "farm" in out["candidates"]
    assert "buy" not in out["candidates"]


def test_death_forces_respawn_subgoal():
    loop = AutonomyLoop()
    info = _info(dead=True)
    out = loop.before_action(info, _ws(info), ["farm"])
    assert out["subgoal"]["subgoal"] == "RESPAWN"


def test_subgoal_is_counted_in_stats():
    loop = AutonomyLoop()
    info = _info()
    loop.before_action(info, _ws(info), ["farm"])
    assert sum(loop.stats["subgoals"].values()) == 1


# ------------------------------------------------------------ after_action

def test_kill_counts_as_success():
    loop = AutonomyLoop()
    before = _info(kills=0)
    loop.before_action(before, _ws(before), ["farm"])
    after = _info(kills=1)
    rec = loop.after_action("farm", after, _ws(after))
    assert rec["skill_result"] == "SUCCESS"
    assert rec["progress_delta"]["kills_delta"] == 1
    assert rec["failure_reason"] is None


def test_nothing_changed_is_no_op_not_success():
    loop = AutonomyLoop()
    info = _info()
    loop.before_action(info, _ws(info), ["farm"])
    rec = loop.after_action("farm", info, _ws(info))
    assert rec["skill_result"] == "NO_OP"
    assert rec["failure_reason"] is not None
    assert rec["recovery"] is not None


def test_death_is_failure():
    loop = AutonomyLoop()
    before = _info(deaths=0)
    loop.before_action(before, _ws(before), ["farm"])
    after = _info(deaths=1)
    rec = loop.after_action("farm", after, _ws(after))
    assert rec["skill_result"] == "FAILURE"


def test_buy_without_inventory_change_is_not_success():
    loop = AutonomyLoop()
    before = _info(copper=20)
    loop.before_action(before, _ws(before), ["buy"])
    # копейки ушли, но предмет не появился -> контракт buy не выполнен
    after = _info(copper=15)
    rec = loop.after_action("buy", after, _ws(after))
    assert rec["skill_result"] != "SUCCESS"
    assert "inventory_changed" in rec["postconditions"]["missing"]


def test_sell_junk_success_on_copper_gain():
    loop = AutonomyLoop()
    before = _info(copper=0, inv=[{"quality": 0}] * 3)
    loop.before_action(before, _ws(before), ["sell_junk"])
    after = _info(copper=12, inv=[])
    rec = loop.after_action("sell_junk", after, _ws(after))
    assert rec["skill_result"] == "SUCCESS"


def test_recovery_escalates_across_repeated_failures():
    loop = AutonomyLoop()
    info = _info()
    seen = []
    for _ in range(3):
        loop.before_action(info, _ws(info), ["buy"])
        rec = loop.after_action("buy", info, _ws(info))
        seen.append(rec["recovery"]["recovery_action"])
    assert len(set(seen)) > 1, seen        # лестница, а не один и тот же шаг


def test_recovery_resets_after_success():
    loop = AutonomyLoop()
    info = _info(kills=0)
    loop.before_action(info, _ws(info), ["farm"])
    loop.after_action("farm", info, _ws(info))            # NO_OP
    after = _info(kills=1)
    loop.before_action(info, _ws(info), ["farm"])
    loop.after_action("farm", after, _ws(after))          # SUCCESS
    loop.before_action(after, _ws(after), ["farm"])
    rec = loop.after_action("farm", after, _ws(after))    # снова NO_OP
    assert rec["recovery"]["attempt"] == 0


# ------------------------------------------------------------- loop control

def test_repeated_no_progress_trips_loop_and_blocks_action():
    loop = AutonomyLoop()
    info = _info()
    for _ in range(4):
        loop.before_action(info, _ws(info), ["buy"])
        loop.after_action("buy", info, _ws(info))
    out = loop.before_action(info, _ws(info), ["buy"])
    assert loop.stats["loops_tripped"] >= 1
    assert "buy" in out["blocked"]


def test_progress_prevents_loop_trip():
    loop = AutonomyLoop()
    kills = 0
    for _ in range(25):
        before = _info(kills=kills)
        loop.before_action(before, _ws(before), ["farm"])
        kills += 1
        after = _info(kills=kills)
        loop.after_action("farm", after, _ws(after))
    assert loop.stats["loops_tripped"] == 0


# ----------------------------------------------------------------- summary

def test_summary_reports_rates():
    loop = AutonomyLoop()
    before = _info(kills=0)
    loop.before_action(before, _ws(before), ["farm"])
    after = _info(kills=1)
    loop.after_action("farm", after, _ws(after))
    loop.before_action(after, _ws(after), ["farm"])
    loop.after_action("farm", after, _ws(after))
    s = loop.summary()
    assert s["steps"] == 2
    assert s["success_rate"] == 0.5
    assert s["no_op_rate"] == 0.5


def test_recovery_map_only_names_real_skills():
    from action_mask import SKILL_INDEX
    allowed = set(SKILL_INDEX) | {"explore", None}
    for rec, skill in RECOVERY_TO_SKILL.items():
        assert skill in allowed, (rec, skill)
