"""Unit tests for the respawn recovery state machine (design: variant A).

These run WITHOUT a live game tab. They mock BrowserEnv._require so the
respawn-recovery branch in Agent._cycle is exercised deterministically:

  - revived=True  -> cycle proceeds to policy.decide() (no pause)
  - revived=False x3 -> cycle returns early with outcome_kind="ENV_ERROR"
                        (RESPAWN_FAILED -> PAUSE, no farm/heal/loot, no lesson)

The integration smoke test (test_respawn_live_smoke) requires a real game tab
on CDP :9222 + bridge on :8791; it SKIPs (not fails) when neither is reachable,
so we never fabricate a "respawn succeeded" result.
"""
import sys
import os
import time

# Make the repo's python/ importable when run from anywhere.
sys.path.insert(0, os.path.dirname(__file__))

from agent import Agent
from browser_env import BrowserBridgeError


def _make_agent(respawn_seq):
    """Build an Agent with a stub env whose respawn() returns items from respawn_seq.

    respawn_seq: list of (info_dict, revived_bool). Each call to env.respawn()
    pops the next item; once exhausted it repeats the last item forever.
    """
    class _StubEnv:
        def __init__(self):
            self._last_info = {"player": {"dead": True, "hp": 0, "maxHp": 100},
                               "nearby": [], "kills": 0, "deaths": 0}
            self._seq = list(respawn_seq)
            self._i = 0
            self.respawn_calls = 0
            self.step_calls = 0

        def respawn(self):
            self.respawn_calls += 1
            info, revived = self._seq[min(self._i, len(self._seq) - 1)]
            self._i += 1
            self._last_info = info
            return info, revived

        def step(self, idx, ctx=None):
            self.step_calls += 1
            return self._last_info

        # attributes Agent/play_autonomous touch
        @property
        def health(self):
            return {"ok": True, "bridge": True, "page": True, "game": True}

    class _StubMem:
        def learn(self, *a, **k):
            pass
        def save(self):
            pass

    class _StubPolicy:
        def decide(self, info, ws=None, goal=None, exploration_weight=1.0):
            return "farm", {}
        def _candidates(self, info, ws=None, goal=None):
            return []
        def learn(self, *a, **k):
            pass

    env = _StubEnv()
    ag = Agent(env, _StubMem())
    ag.policy = _StubPolicy()  # skip real tabular policy randomness
    ag.fsm = None
    ag.replay = None
    ag.strat_mem = None
    return ag, env


def test_respawn_success_proceeds():
    """revived=True -> cycle does not pause; a normal 'farm' action is produced."""
    alive_info = {"player": {"dead": False, "hp": 80, "maxHp": 100},
                  "nearby": [], "kills": 5, "deaths": 1}
    ag, env = _make_agent([(alive_info, True)])
    rec = ag._cycle(learn=True)
    assert rec["outcome_kind"] != "ENV_ERROR", "should not pause when revived"
    assert rec["action"] == "farm", "cycle should proceed to a real skill"
    assert env.respawn_calls == 1, "respawn called exactly once on success"


def test_respawn_failure_pauses_as_env_error():
    """revived=False three times -> early ENV_ERROR return, no skill executed."""
    dead_info = {"player": {"dead": True, "hp": 0, "maxHp": 100},
                 "nearby": [], "kills": 0, "deaths": 3}
    ag, env = _make_agent([(dead_info, False), (dead_info, False), (dead_info, False)])
    rec = ag._cycle(learn=True)
    assert rec["outcome_kind"] == "ENV_ERROR", "RESPAWN_FAILED must pause as ENV_ERROR"
    assert rec["action"] == "recover", "no farm/heal/loot on a stuck corpse"
    assert env.respawn_calls == ag.RESPAWN_MAX_ATTEMPTS, (
        "must retry exactly RESPAWN_MAX_ATTEMPTS times, got %d" % env.respawn_calls)


def test_respawn_success_after_retries():
    """revived=False, False, True -> proceeds (no pause); respawn retried <= max."""
    dead_info = {"player": {"dead": True, "hp": 0, "maxHp": 100}, "nearby": [], "kills": 0, "deaths": 2}
    alive_info = {"player": {"dead": False, "hp": 50, "maxHp": 100}, "nearby": [], "kills": 0, "deaths": 2}
    ag, env = _make_agent([(dead_info, False), (dead_info, False), (alive_info, True)])
    rec = ag._cycle(learn=True)
    assert rec["outcome_kind"] != "ENV_ERROR"
    assert rec["action"] == "farm"
    assert env.respawn_calls <= ag.RESPAWN_MAX_ATTEMPTS


def test_respawn_bridge_down_is_infra_not_programming():
    """A BrowserBridgeError from respawn must propagate as ENV_ERROR path, not crash."""
    class _FailEnv:
        def __init__(self):
            self._last_info = {"player": {"dead": True, "hp": 0, "maxHp": 100}, "nearby": [], "kills": 0, "deaths": 0}
        def respawn(self):
            raise BrowserBridgeError("bridge down")
        def step(self, idx, ctx=None):
            return self._last_info
    class _StubMem:
        def learn(self, *a, **k): pass
        def save(self): pass
    ag = Agent(_FailEnv(), _StubMem())
    ag.policy = type("P", (), {"decide": lambda *a, **k: ("farm", {}), "learn": lambda *a, **k: None})()
    ag.fsm = None; ag.replay = None; ag.strat_mem = None
    # The recovery branch calls respawn() inside a try? No — it is NOT wrapped, so a
    # BrowserBridgeError here is infra and should be caught by play_autonomous's
    # except BrowserBridgeError, yielding ENV_ERROR. We assert it propagates (does
    # not become a ProgrammingError / AttributeError).
    try:
        ag._cycle(learn=True)
        assert False, "expected BrowserBridgeError to propagate"
    except BrowserBridgeError:
        pass  # correct: infra, not masked


def test_respawn_live_smoke():
    """Integration smoke: force death -> respawn -> verify revived via real bridge.

    Requires a live game tab (CDP :9222) and the bridge (:8791). SKIPPED when not
    reachable so CI / offline runs never fabricate a success. Mirrors the user's
    requested smoke-test: poll distance/dead/hp instead of trusting ok:true.
    """
    import socket
    import json
    import urllib.request

    def _bridge_up():
        try:
            with socket.create_connection(("127.0.0.1", 8791), timeout=1.0):
                return True
        except OSError:
            return False

    if not _bridge_up():
        import pytest
        pytest.skip("bridge :8791 not reachable — needs a live game tab; cannot fabricate respawn result")

    # Only reached with a real bridge+game. Drive the real respawn and assert the
    # bridge reports revived AND the snapshot shows an alive player.
    import browser_env
    env = browser_env.BrowserEnv()
    info, revived = env.respawn()
    p = (info or {}).get("player", {})
    assert revived is True, "bridge must report real revival"
    assert p.get("dead") is False, "player must not be dead after revive"
    assert (p.get("hp") or 0) > 0, "player must have hp>0 after revive"


if __name__ == "__main__":
    # allow plain `python test_respawn_recovery.py` without pytest installed
    import unittest
    unittest.main()
