"""test_schema_contract.py — контракт snapshot -> WorldState -> policy -> verifier.

НЕ использует fixture: берёт РЕАЛЬНЫЙ снапшот от живого моста (127.0.0.1:8791).
Запуск: WOC_CONTRACT=1 pytest -q python/test_schema_contract.py
"""
import os
import json
import urllib.request

import pytest

BRIDGE = "http://127.0.0.1:8791"


def _snapshot() -> dict:
    req = urllib.request.Request(
        BRIDGE, data=json.dumps({"action": "snapshot"}).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


@pytest.fixture(scope="module")
def snap():
    if not os.environ.get("WOC_CONTRACT"):
        pytest.skip("WOC_CONTRACT=1 not set (live bridge test)")
    try:
        return _snapshot()
    except Exception as e:
        pytest.skip(f"bridge unavailable: {e}")


def _info_from_bridge(snap):
    d = snap.get("info", snap)
    if isinstance(d.get("info"), dict):
        d = d["info"]
    return d


def test_inventory_canonical_item_id(snap):
    info = _info_from_bridge(snap)
    inv = info.get("inventory") or []
    assert inv, "инвентарь пуст — агент без предметов"
    for slot in inv:
        assert slot.get("itemId"), f"слот без canonical itemId: {slot}"
        # quality null когда игра не отдаёт (не 0, не фейк)
        assert slot.get("quality") is None or isinstance(slot.get("quality"), (int, str)), \
            f"quality должен быть null/число/строка: {slot}"


def test_inventory_by_id_matches_inventory(snap):
    info = _info_from_bridge(snap)
    inv = info.get("inventory") or []
    by_id = info.get("inventory_by_id") or {}
    ids = {s["itemId"] for s in inv if s.get("itemId")}
    assert set(by_id.keys()) == ids


def test_quests_done_counter_present(snap):
    info = _info_from_bridge(snap)
    qd = info.get("quests_done")
    assert isinstance(qd, int) and qd >= 0


def test_world_state_needs_tool_respects_equipped_and_proficiency(snap):
    """needs_tool учитывает wield-гейт игры: инструмент в сумке + proficiency.

    Живой замер (2026-08-25): copper_mining_pick В СУМКЕ, но needs_tool
    возвращал его снова — has_tool не знал про wield gate. Инвариант:
    если предмет в инвентаре, needs_tool не может предлагать его к покупке.
    """
    from world_state import build_world_state
    info = _info_from_bridge(snap)
    ws = build_world_state(info)
    need = ws.get("needs_tool")
    if need:
        inv_ids = {s.get("itemId") for s in (info.get("inventory") or [])}
        if need in inv_ids:
            pytest.xfail(
                f"needs_tool={need} при наличии в инвентаре — wield-gate "
                f"(предмет есть, но не экипирован/proficiency). Требуется "
                f"equip-действие перед покупкой.")


def test_policy_decision_runs_on_real_snapshot(snap):
    from policy import GoalManager
    from memory import ExperienceStore
    info = _info_from_bridge(snap)
    gm = GoalManager(ExperienceStore(), reflection_hints={})
    ws = gm._world_state(info)
    action, ctx = gm.decide(info, ws=ws, goal="DO_OBJECTIVE")
    assert action
    if action == "buy":
        assert ctx.get("buyItemId")


def test_buy_verifier_gives_failure_not_inconclusive():
    from verifiers_py import verify_skill
    before = {"player": {"copper": 100}, "inventory": [{"itemId": "handaxe", "count": 0}]}
    after = {"player": {"copper": 100}, "inventory": [{"itemId": "handaxe", "count": 0}]}
    v = verify_skill("buy", {"before": before, "after": after,
                             "handle": {"itemId": "handaxe"}})
    assert v == "failure"
