"""test_browser_base_turnin.py — BrowserBase.turn_in_quest существует и работает.

Корень 1785 FAIL подряд (2026-08-25): quest_capability.turn_in вызывал
env.base.turn_in_quest(qid), но у BrowserBase этого метода не было ->
AttributeError -> except -> FAILURE. Ручной sim.turnInQuest тем же qid
проходил мгновенно.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))


class _FakeRequireEnv:
    """Ловит payload вместо реального HTTP."""
    def __init__(self):
        self.payloads = []
        self._last_info = {}

    def _require(self, payload, timeout=30.0):
        self.payloads.append(payload)
        return {"ok": True, "info": {"quests": {"done": ["q_greyjaw"]}}}


def test_browser_base_has_turn_in_quest():
    from browser_env import BrowserBase
    assert hasattr(BrowserBase, "turn_in_quest"), \
        "BrowserBase обязан иметь turn_in_quest — иначе каждая сдача = FAILURE"


def test_turn_in_quest_sends_idx3_with_questid():
    from browser_env import BrowserBase
    env = _FakeRequireEnv()
    base = BrowserBase(env)
    out = base.turn_in_quest("q_greyjaw")
    assert len(env.payloads) == 1
    p = env.payloads[0]
    assert p["action"] == "step"
    assert p["idx"] == 3
    assert p["questId"] == "q_greyjaw"
    # info обновлён на env
    assert env._last_info.get("quests", {}).get("done") == ["q_greyjaw"]
    assert out is env._last_info


def test_capability_turn_in_succeeds_with_fixed_base(tmp_path=None):
    """Полная цепочка: capability.turn_in -> base.turn_in_quest -> SUCCESS."""
    from quest_capability import QuestCapability

    class FakeBase:
        def turn_in_quest(self, qid):
            return {"quests": {"done": [qid]}}

    class FakeEnv:
        _last_info = {}
        base = FakeBase()

    cap = QuestCapability(FakeEnv())
    res = cap.turn_in({"id": "q_greyjaw"})
    assert res == "SUCCESS"
