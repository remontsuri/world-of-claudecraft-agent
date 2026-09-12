"""Regression tests for skill_forge.py.

No network access — all LLM calls are mocked. This tests the parts that are
this project's responsibility: the safety gate, the sandbox, and the
propose->verify->refine loop wiring to SkillLibrary. It does NOT test whether
a real LLM produces good code — that's an integration/live concern, not a
unit-test concern (per project rule: don't claim "learned"/"works" without
matching evidence level).
"""

import os
import tempfile

import pytest

import skill_forge as sf
from skill_library import SkillLibrary


# --------------------------------------------------------------- safety gate


@pytest.mark.parametrize(
    "code",
    [
        "import os\ndef skill_impl(cap, ctx):\n    return {}",
        "import subprocess\ndef skill_impl(cap, ctx):\n    return {}",
        "def skill_impl(cap, ctx):\n    return cap.__class__.__bases__",
        "def skill_impl(cap, ctx):\n    return eval('1+1')",
        "def skill_impl(cap, ctx):\n    return exec('x=1')",
        "def skill_impl(cap, ctx):\n    return open('secrets.txt').read()",
        "def helper():\n    pass\ndef skill_impl(cap, ctx):\n    return helper()",
        "class Foo:\n    pass\ndef skill_impl(cap, ctx):\n    return {}",
        "def skill_impl(cap, ctx):\n    global x\n    return {}",
        "x = 1\ndef skill_impl(cap, ctx):\n    return x",
    ],
)
def test_static_safety_check_rejects_unsafe_code(code):
    assert sf._static_safety_check(code) is not None


def test_static_safety_check_accepts_valid_skill_code():
    code = (
        "def skill_impl(cap, ctx):\n"
        "    q = cap.find_active_quest()\n"
        '    return {"quest": q, "hp": ctx.get("hp_frac")}'
    )
    assert sf._static_safety_check(code) is None


# ----------------------------------------------------------------- sandbox


class _FakeCap:
    def find_active_quest(self):
        return {"id": "q_test"}


def test_sandbox_executes_valid_code_and_returns_result():
    code = (
        "def skill_impl(cap, ctx):\n"
        "    q = cap.find_active_quest()\n"
        '    return {"quest": q, "hp": ctx.get("hp_frac")}'
    )
    result, err = sf._execute_sandboxed(code, _FakeCap(), {"hp_frac": 0.8})
    assert err is None
    assert result == {"quest": {"id": "q_test"}, "hp": 0.8}


def test_sandbox_times_out_on_infinite_loop_instead_of_hanging():
    code = "def skill_impl(cap, ctx):\n    while True:\n        pass\n"
    import time

    t0 = time.time()
    result, err = sf._execute_sandboxed(code, _FakeCap(), {}, timeout_s=1.0)
    dt = time.time() - t0
    assert result is None
    assert err is not None and "timeout" in err
    assert dt < 2.0  # must not actually block for the infinite loop's lifetime


def test_sandbox_reports_runtime_errors_without_crashing_caller():
    code = "def skill_impl(cap, ctx):\n    return 1 / 0\n"
    result, err = sf._execute_sandboxed(code, _FakeCap(), {})
    assert result is None
    assert "ZeroDivisionError" in err


def test_sandbox_does_not_mutate_callers_ctx():
    """ctx is passed as a deep copy so a forged skill can't corrupt live
    world_state even if it tries to mutate the dict it was given.
    """
    code = "def skill_impl(cap, ctx):\n    ctx['hp_frac'] = -999\n    return ctx"
    original = {"hp_frac": 1.0}
    sf._execute_sandboxed(code, _FakeCap(), original)
    assert original["hp_frac"] == 1.0


# --------------------------------------------------------------- full loop


class _MockLLM:
    """Scripted responses: first attempt unsafe, second attempt correct."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, system, user, max_tokens=1200):
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


def _fresh_library():
    path = os.path.join(tempfile.mkdtemp(), "lib.json")
    return SkillLibrary(path)


def test_forge_skill_retries_after_unsafe_code_then_accepts():
    llm = _MockLLM(
        [
            "def skill_impl(cap, ctx):\n    import os\n    return {}",
            'def skill_impl(cap, ctx):\n    return {"ok": True}',
        ]
    )
    lib = _fresh_library()
    forge = sf.SkillForge(lib, llm=llm, max_attempts=3, exec_timeout_s=2.0)
    gap = sf.SkillGap(goal="test_gap", description="test", context_keys=[])
    result = forge.forge_skill(
        gap, _FakeCap(), {}, verifier=lambda c: "success", snapshot_fn=lambda: {}
    )
    assert result.accepted is True
    assert len(result.attempts) == 2
    assert result.attempts[0].static_error is not None
    assert result.attempts[1].accepted is True
    assert result.final_skill_id == "forged_test_gap"
    saved = lib.get("forged_test_gap")
    assert saved is not None
    assert saved.success_count == 1
    assert "ok" in saved.implementation


def test_forge_skill_gives_up_after_max_attempts_without_writing_broken_skill():
    """Per 'no fake success' rule: if the verifier never says success, nothing
    gets written to the library, even after burning the whole attempt budget.
    """
    llm = _MockLLM(
        [
            'def skill_impl(cap, ctx):\n    return {"ok": True}',
        ]
    )
    lib = _fresh_library()
    forge = sf.SkillForge(lib, llm=llm, max_attempts=2, exec_timeout_s=2.0)
    gap = sf.SkillGap(goal="never_works", description="test", context_keys=[])
    result = forge.forge_skill(
        gap, _FakeCap(), {}, verifier=lambda c: "inconclusive", snapshot_fn=lambda: {}
    )
    assert result.accepted is False
    assert result.final_skill_id is None
    assert len(result.attempts) == 2
    assert lib.get("forged_never_works") is None


def test_forge_skill_stops_immediately_on_llm_call_error_without_retrying():
    class _BrokenLLM:
        def complete(self, system, user, max_tokens=1200):
            raise sf.LLMCallError("no API key configured")

    lib = _fresh_library()
    forge = sf.SkillForge(lib, llm=_BrokenLLM(), max_attempts=3)
    gap = sf.SkillGap(goal="x", description="x", context_keys=[])
    result = forge.forge_skill(
        gap, _FakeCap(), {}, verifier=lambda c: "success", snapshot_fn=lambda: {}
    )
    assert result.accepted is False
    assert len(result.attempts) == 1  # did not burn the whole retry budget on a config error
