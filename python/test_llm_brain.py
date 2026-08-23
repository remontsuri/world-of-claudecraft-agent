import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import llm_brain
from llm_brain import LLMBrain


class FakeResp:
    def __init__(self, payload): self._p = json.dumps(payload).encode()
    def read(self): return self._p
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _ok_content(goal="DO_OBJECTIVE", reason="r"):
    return {"choices": [{"message": {"content": json.dumps({"goal": goal, "reason": reason})}}]}


def test_decide_parses_valid():
    b = LLMBrain(base_url="http://mock")
    captured = {}
    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode())
        return FakeResp(_ok_content("TURN_IN", "ready and near"))
    llm_brain.urllib.request.urlopen = fake_urlopen
    out = b.decide({"quest": {"phase": "READY"}}, [], [])
    assert out == {"goal": "TURN_IN", "reason": "ready and near"}
    rf = captured["body"]["response_format"]
    assert rf["type"] == "json_schema"
    enum = rf["json_schema"]["schema"]["properties"]["goal"]["enum"]
    assert set(enum) == set(llm_brain.GOALS)
    assert captured["body"]["temperature"] == 0.0


def test_invalid_goal_returns_none():
    b = LLMBrain(base_url="http://mock")
    llm_brain.urllib.request.urlopen = lambda req, timeout: FakeResp(
        _ok_content("CONQUER_WORLD"))
    assert b.decide({}, [], []) is None


def test_garbage_json_returns_none():
    b = LLMBrain(base_url="http://mock")
    llm_brain.urllib.request.urlopen = lambda req, timeout: FakeResp(
        {"choices": [{"message": {"content": "не JSON вообще"}}]})
    assert b.decide({}, [], []) is None


def test_timeout_returns_none():
    b = LLMBrain(base_url="http://mock", timeout=0.05)
    def slow(req, timeout): raise TimeoutError("too slow")
    llm_brain.urllib.request.urlopen = slow
    assert b.decide({}, [], []) is None


def test_prompt_contains_world_and_failures():
    b = LLMBrain(base_url="http://mock")
    seen = {}
    def fake(req, timeout):
        seen["body"] = json.loads(req.data.decode()); return FakeResp(_ok_content())
    llm_brain.urllib.request.urlopen = fake
    b.decide({"quest": {"id": "q_bones", "phase": "ACTIVE"}},
             [{"action": "turn_in_quest", "result": "FAILURE",
               "reason": "wrong_npc"}],
             ["IF phase==ACTIVE THEN never ACCEPT"])
    user_msg = seen["body"]["messages"][-1]["content"]
    assert "q_bones" in user_msg and "wrong_npc" in user_msg and "never ACCEPT" in user_msg
