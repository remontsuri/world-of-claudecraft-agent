"""test_autonomy_e2e.py — full-stack E2E против ЖИВОЙ игры (аудит P0.8).

Ревью: «отсутствует тест вида REAL CLIENT -> REAL BRIDGE -> REAL SNAPSHOT ->
WORLD STATE -> PLANNER -> ACTION MASK -> REAL SKILL -> REAL GAME MUTATION ->
PROGRESS -> VERIFIER». Вот он.

Это НЕ unit-тест: он требует запущенный мост и по умолчанию скипается.
    WOC_E2E=1 python -m pytest test_autonomy_e2e.py -v -s

Правило файла: НИЧЕГО не мокается. Если сценарий недостижим в текущем
состоянии мира — тест SKIP с причиной, а не «зелёный на всякий случай».
Мутации подтверждаются дельтой снапшота, а не тем, что мост ответил ok.
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from action_mask import endpoint_of, get_action_mask, index_of, mask_candidates
from autonomy import AutonomyLoop
from observation import encode_observation
from planner import plan_subgoals
from progress import classify_outcome, detect_progress
from skill_contracts import check_preconditions, verify_postconditions
from world_state import build_world_state

BRIDGE = os.environ.get("WOC_BRIDGE", "http://127.0.0.1:8791")
ENABLED = os.environ.get("WOC_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not ENABLED, reason="live E2E: set WOC_E2E=1 with the bridge running")


# ------------------------------------------------------------------ helpers

def call(payload, timeout=120):
    req = urllib.request.Request(
        BRIDGE, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    raw = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    info = raw.get("info") or {}
    if "info" in info:                      # мост иногда вкладывает дважды
        info = info["info"]
    return raw, info


def snapshot():
    _, info = call({"action": "snapshot"})
    return info


def observe(info=None):
    info = info or snapshot()
    ws = build_world_state(info)
    return ws, encode_observation(ws, info), info


def run_skill(skill, ctx=None):
    """Выполнить навык через ПРАВИЛЬНЫЙ канал моста и вернуть (before, after)."""
    _, before = call({"action": "snapshot"})
    ep = endpoint_of(skill)
    if ep == "navigate":
        payload = dict({"action": "navigate"}, **(ctx or {}))
    elif ep:
        payload = dict({"action": ep}, **(ctx or {}))
    else:
        payload = dict({"action": "step", "idx": index_of(skill)}, **(ctx or {}))
    _, after = call(payload, timeout=180)
    return before, after


def progress_of(before_info, after_info):
    ws_b, obs_b, _ = observe(before_info)
    ws_a, obs_a, _ = observe(after_info)
    return detect_progress(obs_b, obs_a), obs_b, obs_a


@pytest.fixture(scope="module")
def bridge_up():
    try:
        info = snapshot()
    except Exception as exc:
        pytest.skip("bridge not reachable at %s: %s" % (BRIDGE, exc))
    if not info:
        pytest.skip("bridge returned an empty snapshot")
    return info


# ------------------------------------------------- E2E-0: контракт снапшота

def test_e2e_0_snapshot_carries_canonical_fields(bridge_up):
    """Без этих полей все остальные сценарии измеряют мусор."""
    info = bridge_up
    assert isinstance(info.get("inventory_by_id"), dict), "нет canonical инвентаря"
    assert isinstance(info.get("equipment"), dict), "нет canonical экипировки"
    assert info.get("player_class"), "мост не отдаёт класс игрока"

    ws, obs, _ = observe(info)
    assert obs["inventory"]["items"] == info["inventory_by_id"]
    assert obs["inventory"]["equipment"] == info["equipment"]
    print("\n  class=%s items=%s equip=%s" % (
        obs["player"]["player_class"], obs["inventory"]["items"],
        obs["inventory"]["equipment"]))


def test_e2e_0b_plan_is_derived_from_live_state(bridge_up):
    """Планировщик работает на живом состоянии и выдаёт исполнимую цепочку."""
    _, obs, _ = observe()
    plan = plan_subgoals(obs)
    assert plan, "планировщик не смог составить план на живом состоянии"
    for step in plan:
        assert step.get("skill"), "шаг плана без навыка: %r" % step
    print("\n  plan:", [(s["subgoal"], s["skill"]) for s in plan])


# ------------------------------------------------------- E2E-1: dead -> alive

def test_e2e_1_respawn_when_dead(bridge_up):
    _, obs, info = observe()
    if not obs["player"]["dead"]:
        pytest.skip("персонаж жив — сценарий смерти недостижим без урона")

    plan = plan_subgoals(obs)
    assert plan[0]["subgoal"] == "RESPAWN", plan
    assert plan[0]["skill"] == "respawn", "смерть должна вести к respawn"

    before, after = run_skill("respawn")
    prog, obs_b, obs_a = progress_of(before, after)
    assert prog["became_alive"] is True, "respawn не воскресил персонажа"
    assert verify_postconditions("respawn", prog)["result"] == "SUCCESS"
    print("\n  respawn: dead=%s -> dead=%s" % (
        obs_b["player"]["dead"], obs_a["player"]["dead"]))


# --------------------------------------- E2E-2: инструмент -> вендор -> покупка

def test_e2e_2_tool_chain_is_consistent_end_to_end(bridge_up):
    """objective.toolItemId -> needs_tool -> planner -> ctx.buyItemId -> цена.

    Ровно та цепочка, которая была production-баго м: id инструмента обязан
    совпадать на всех уровнях, а цена — быть известной ДО покупки.
    """
    ws, obs, info = observe()
    tool = ws.get("needs_tool")
    if not tool:
        pytest.skip("сейчас инструмент не требуется ни одним объективом")

    assert obs["inventory"]["missing_tool"] == tool, "planner увидит другой id"
    assert tool not in (obs["inventory"]["items"] or {}), \
        "needs_tool указывает на то, что уже в сумке"

    price = obs["inventory"]["buy_item_price"]
    assert price is not None, "цена инструмента неизвестна -> BUY обречён"
    copper = obs["player"]["copper"]
    pre = check_preconditions("buy", obs)
    if copper < price:
        assert "money_sufficient" in pre["failed"], \
            "денег не хватает, но контракт этого не видит"
        print("\n  tool=%s price=%s copper=%s -> BUY корректно заблокирован"
              % (tool, price, copper))
    else:
        print("\n  tool=%s price=%s copper=%s -> BUY разрешён"
              % (tool, price, copper))


def test_e2e_2b_buy_mutates_inventory_or_fails_honestly(bridge_up):
    """Если BUY разрешён — покупка обязана изменить инвентарь и медь."""
    _, obs, _ = observe()
    if not check_preconditions("buy", obs)["ok"]:
        pytest.skip("BUY заблокирован контрактом: %s"
                    % check_preconditions("buy", obs)["failed"])

    item = obs["inventory"]["buy_item_id"]
    before, after = run_skill("buy", {"buyItemId": item})
    prog, obs_b, obs_a = progress_of(before, after)
    got = (prog["items_delta"] or {}).get(item, 0)
    assert got > 0 or prog["copper_delta"] < 0, \
        "мост принял BUY, но ни инвентарь, ни медь не изменились"
    print("\n  buy %s: items_delta=%s copper_delta=%s"
          % (item, prog["items_delta"], prog["copper_delta"]))


# ------------------------------------------ E2E-3: objective -> turn_in -> done

def test_e2e_3_turn_in_increments_completed_quests(bridge_up):
    _, obs, _ = observe()
    if (obs["quest"]["ready"] or 0) <= 0:
        pytest.skip("нет готового к сдаче квеста")

    pre = check_preconditions("turn_in_quest", obs)
    if not pre["ok"]:
        # это законный результат: сдавать некуда, надо идти к гиверу
        assert "giver_reachable" in pre["failed"] or "giver_exists" in pre["failed"]
        pytest.skip("гивер недостижим: %s" % pre["failed"])

    before, after = run_skill("turn_in_quest")
    prog, _, _ = progress_of(before, after)
    assert prog["quests_done_delta"] > 0, "сдача квеста не увеличила счётчик"
    print("\n  turn_in: quests_done +%d" % prog["quests_done_delta"])


# ------------------------------------------ E2E-4: навигация к квестовому мобу

def test_e2e_4_navigation_closes_distance_to_quest_target(bridge_up):
    _, obs, _ = observe()
    nxt = obs["quest"]["next_objective"] or {}
    if (nxt.get("type") or "") != "kill":
        pytest.skip("активный объектив не kill: %r" % (nxt.get("type"),))
    if not obs["target"]["exists"]:
        pytest.skip("целей в зоне видимости нет")

    # цель должна быть КВЕСТОВОЙ, а не просто ближайшей
    if nxt.get("target_mob_id"):
        assert obs["target"]["quest_mob_id"] == nxt["target_mob_id"]

    loop = AutonomyLoop(min_dwell=1)
    ws, _, info = observe()
    pre = loop.before_action(info, ws, ["farm", "explore"])
    cmd = pre.get("nav_command")
    if not cmd:
        pytest.skip("контур решил, что навигация не нужна (status=%s)"
                    % pre.get("nav_status"))

    d0 = obs["target"]["distance"]
    _, after = call(cmd, timeout=180)
    _, obs_a, _ = observe(after)
    d1 = obs_a["target"]["distance"]
    assert d1 < d0 or obs_a["target"]["in_melee_range"], \
        "навигация не сократила дистанцию: %.1f -> %.1f" % (d0, d1)
    print("\n  nav: %.1f -> %.1f yd" % (d0, d1))


# --------------------------------- E2E-5: отказ -> recovery -> нет вечного цикла

def test_e2e_5_failure_triggers_executable_recovery(bridge_up):
    """Заведомо невозможное действие обязано дать ИСПОЛНИМЫЙ recovery."""
    loop = AutonomyLoop(min_dwell=1)
    ws, obs, info = observe()

    # ищем навык, который сейчас точно заблокирован
    blocked = [s for s in ("buy", "gather", "turn_in_quest", "loot")
               if not check_preconditions(s, obs)["ok"]]
    if not blocked:
        pytest.skip("все навыки сейчас исполнимы — нечего валить")
    skill = blocked[0]

    loop.before_action(info, ws, [skill, "explore"])
    rec = loop.after_action(skill, info, ws)

    assert rec["skill_result"] != "SUCCESS"
    assert rec["failure_reason"], "отказ без причины"
    plan = (rec["recovery"] or {}).get("plan")
    assert plan, "recovery не транслирован в исполнимое действие"
    assert plan["kind"] in ("skill", "navigate", "control")
    print("\n  %s -> %s -> recovery=%s plan=%s" % (
        skill, rec["failure_reason"],
        rec["recovery"]["recovery_action"], plan))


def test_e2e_5b_repeated_failure_does_not_loop_forever(bridge_up):
    """Один и тот же отказ N раз обязан привести к смене поведения."""
    loop = AutonomyLoop(min_dwell=1)
    ws, obs, info = observe()
    blocked = [s for s in ("buy", "gather", "turn_in_quest") 
               if not check_preconditions(s, obs)["ok"]]
    if not blocked:
        pytest.skip("нет заблокированных навыков")
    skill = blocked[0]

    seen = []
    for _ in range(6):
        pre = loop.before_action(info, ws, [skill, "explore"])
        seen.append(pre["forced_skill"])
        loop.after_action(skill, info, ws)

    escalated = (loop.stats.get("loops_tripped", 0) > 0
                 or loop.stats.get("recoveries_executed", 0) > 0
                 or loop.stats.get("abandoned", 0) > 0
                 or loop.stats.get("blacklist_skips", 0) > 0)
    assert escalated, ("шесть одинаковых отказов не вызвали ни одной эскалации: %s"
                       % loop.stats)
    print("\n  forced: %s\n  stats: loops=%s rec_exec=%s abandoned=%s" % (
        seen, loop.stats.get("loops_tripped"),
        loop.stats.get("recoveries_executed"), loop.stats.get("abandoned")))
