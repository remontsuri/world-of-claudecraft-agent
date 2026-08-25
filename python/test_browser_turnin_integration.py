"""Live integration/regression test for BrowserBase.turn_in_quest.

Unlike test_browser_base_turnin.py, this test does NOT mock the bridge. It
drives the real HTTP bridge -> actions.step -> GameClient ->
window.__game.sim.turnInQuest() path and verifies the resulting quest state.

Opt-in because it mutates the live character by completing one ready quest:
    WOC_INTEGRATION=1 pytest -q python/test_browser_turnin_integration.py

Optional deterministic quest:
    WOC_INTEGRATION_QUEST_ID=q_greyjaw
"""

import os

import pytest

from browser_env import BrowserBridgeError, BrowserEnv


pytestmark = pytest.mark.integration


def _quest_ids(value):
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(x) for x in value}
    return set()


def _select_ready_quest(info):
    requested = os.getenv("WOC_INTEGRATION_QUEST_ID")
    ready = [q for q in (info.get("quests", {}).get("ready") or []) if q.get("id")]

    if requested:
        match = next((q for q in ready if str(q["id"]) == requested), None)
        assert match is not None, (
            f"WOC_INTEGRATION_QUEST_ID={requested!r} is not READY; "
            f"ready={[q.get('id') for q in ready]!r}"
        )
        return match

    for quest in ready:
        qid = str(quest["id"])
        if any(qid in _quest_ids(npc.get("questIds")) for npc in info.get("nearby", [])):
            return quest

    pytest.fail(
        "No READY quest with a discoverable turn-in NPC in the live snapshot. "
        "Move the character near its giver or set WOC_INTEGRATION_QUEST_ID. "
        f"ready={[q.get('id') for q in ready]!r}"
    )


def test_live_turn_in_quest_reaches_sim_and_marks_quest_done():
    """Regression: the real turn-in command must reach sim.turnInQuest(qid)."""
    if os.getenv("WOC_INTEGRATION") != "1":
        pytest.skip("live bridge test is opt-in; set WOC_INTEGRATION=1")

    env = BrowserEnv()
    try:
        before = env._last_info or {}
        quest = _select_ready_quest(before)
        qid = str(quest["id"])

        giver = next(
            (
                npc
                for npc in (before.get("nearby") or [])
                if npc.get("kind") == "npc"
                and qid in _quest_ids(npc.get("questIds"))
                and npc.get("x") is not None
                and npc.get("z") is not None
            ),
            None,
        )
        assert giver is not None, f"No live giver found for ready quest {qid!r}"

        arrived = env._navigate_to_coord(
            float(giver["x"]), float(giver["z"]), max_steps=80, timeout=90.0
        )
        assert arrived, f"Could not reach turn-in NPC for ready quest {qid!r}"

        # No mock/direct JS call: BrowserBase -> HTTP bridge -> actions.step
        # (idx=3, questId) -> GameClient.evaluate -> sim.turnInQuest(qid).
        result = env.base.turn_in_quest(qid)
        assert isinstance(result, dict), "turn_in_quest must return refreshed info"

        after = env._last_info or result
        done_ids = {
            str(q.get("id")) for q in (after.get("quests", {}).get("done") or [])
        }
        ready_ids = {
            str(q.get("id")) for q in (after.get("quests", {}).get("ready") or [])
        }

        assert qid in done_ids, (
            f"turn_in_quest returned without marking {qid!r} done; "
            f"done={sorted(done_ids)!r}, ready={sorted(ready_ids)!r}"
        )
        assert qid not in ready_ids, f"quest {qid!r} remained READY after turn-in"
    except BrowserBridgeError as exc:
        pytest.fail(f"live browser bridge unavailable or rejected turn-in: {exc}")
    finally:
        env.close()
