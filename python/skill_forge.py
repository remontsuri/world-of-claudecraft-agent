"""skill_forge.py — Voyager-style LLM skill authoring for the WoC agent.

Voyager (Wang et al. 2023) has three pieces: (1) an automatic curriculum that
picks what to try next, (2) a skill library storing REAL EXECUTABLE CODE per
skill, and (3) an iterative prompting loop: generate code -> execute -> read
environment/verifier feedback -> if it failed, feed the failure back to the
LLM and ask it to fix its own code -> retry, up to a budget.

This module implements piece (3), wired to the two pieces that already exist
in this repo but were never connected to anything:

    curriculum.py      -> decides WHEN a new skill is worth forging (a gap)
    skill_library.py   -> stores the resulting Skill, WITH the actual code

SECURITY (per project rule #11 — SECURITY profile, "learned skill -> load ->
execute": нельзя допускать произвольное выполнение непроверенного кода):

  This is a COOPERATIVE sandbox, not an airtight one. It defends against
  careless/buggy LLM-generated code (the common case), NOT against an actively
  adversarial model provider. Two layers:

    1. STATIC AST GATE (_static_safety_check) — the generated source is parsed
       and rejected outright if it contains: any import, any dunder-name
       access/assignment, exec/eval/compile, open/os/sys/subprocess/socket
       names, or a class/function definition other than the single required
       ``def skill_impl(cap, ctx):``.

    2. RESTRICTED EXECUTION (_execute_sandboxed) — the code that passes the
       gate is exec()'d with a minimal __builtins__ allow-list and ONLY the
       QuestCapability instance (``cap``) plus a read-only observation dict
       (``ctx``) injected as names. No filesystem, no network, no subprocess
       object is ever reachable from inside generated code — those calls
       would already have been rejected by the AST gate, but the restricted
       globals are a second, independent line of defense in case the gate has
       a gap.

    3. TIME BUDGET — run on a daemon thread with .join(timeout). If it doesn't
       return in time we mark the attempt FAILED and move on. This does NOT
       kill the thread (Python cannot force-kill a thread); a genuinely
       malicious infinite loop would keep burning a background thread. Full
       isolation would require running generated code in a separate process
       with an IPC proxy for ``cap`` calls — noted as a known limitation, not
       implemented here because QuestCapability holds a live BrowserEnv
       connection that is not safely picklable across a process boundary.

  A generated skill is NEVER written into skill_library.json until it has
  PASSED a real verifier (verifiers_py.py contract) against real before/after
  world state — matching project rule "no fake success" (§ auditor checklist).

LLM CALL FREQUENCY (per project rule §12 — LLM must not be in the hot loop):

  forge_skill() is expensive (network call + sandboxed live game actions) and
  is meant to be invoked ONLY from curriculum.py's gap-detection hook, not
  from the per-tick decision loop. See curriculum.maybe_request_skill_gap()
  wiring note at the bottom of this file.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from skill_library import Skill, SkillLibrary

REQUIRED_FUNC_NAME = "skill_impl"

# ---------------------------------------------------------------- data types


@dataclass
class SkillGap:
    """Describes a capability the agent is missing."""

    goal: str
    description: str
    context_keys: List[str] = field(default_factory=list)
    example_failure: Optional[str] = None


@dataclass
class ForgeAttempt:
    attempt_no: int
    code: str
    static_error: Optional[str] = None
    exec_error: Optional[str] = None
    verifier_verdict: Optional[str] = None
    accepted: bool = False


@dataclass
class ForgeResult:
    goal: str
    accepted: bool
    attempts: List[ForgeAttempt]
    final_skill_id: Optional[str] = None


# --------------------------------------------------------------- LLM client


class LLMCallError(RuntimeError):
    pass


class _AnthropicClient:
    """Minimal HTTP client for api.anthropic.com/v1/messages."""

    def __init__(self, model: Optional[str] = None, timeout_s: float = 30.0):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("SKILL_FORGE_MODEL", "claude-sonnet-4-20250514")
        self.timeout_s = timeout_s

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str:
        if not self.api_key:
            raise LLMCallError(
                "ANTHROPIC_API_KEY not set — skill_forge cannot call the LLM. "
                "Set it in the environment before invoking forge_skill()."
            )
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise LLMCallError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
        except urllib.error.URLError as e:
            raise LLMCallError(f"network error calling api.anthropic.com: {e}")
        parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
        return "".join(parts)


# ------------------------------------------------------------- static gate

_FORBIDDEN_NAMES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
    "importlib",
    "builtins",
    "__builtins__",
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "globals",
    "locals",
    "vars",
    "exit",
    "quit",
    "help",
    "__import__",
}


def _static_safety_check(code: str) -> Optional[str]:
    """Return an error string if `code` is unsafe/malformed, else None."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return f"syntax error: {e}"

    top_level_funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(tree.body) != 1 or len(top_level_funcs) != 1:
        return (
            f"expected exactly one top-level `def {REQUIRED_FUNC_NAME}(cap, ctx):` "
            f"and nothing else at module scope"
        )
    if top_level_funcs[0].name != REQUIRED_FUNC_NAME:
        return f"top-level function must be named {REQUIRED_FUNC_NAME!r}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return f"import is forbidden: {ast.dump(node)[:120]}"
        if isinstance(node, ast.ClassDef):
            return "class definitions are forbidden"
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return "global/nonlocal is forbidden"
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            return f"forbidden name used: {node.id}"
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                return f"dunder attribute access is forbidden: .{node.attr}"
            if node.attr in _FORBIDDEN_NAMES:
                return f"forbidden attribute access: .{node.attr}"
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in ("exec", "eval", "compile"):
                return f"forbidden call: {fn.id}(...)"
    return None


_SAFE_BUILTINS: Dict[str, Any] = {
    name: getattr(__builtins__, name) if not isinstance(__builtins__, dict) else __builtins__.get(name)
    for name in (
        "abs",
        "min",
        "max",
        "len",
        "range",
        "enumerate",
        "sorted",
        "reversed",
        "sum",
        "any",
        "all",
        "zip",
        "map",
        "filter",
        "list",
        "dict",
        "set",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "None",
        "True",
        "False",
        "isinstance",
        "print",
    )
    if (isinstance(__builtins__, dict) and name in __builtins__)
    or (not isinstance(__builtins__, dict) and hasattr(__builtins__, name))
}


def _execute_sandboxed(code: str, cap: Any, ctx: dict, timeout_s: float = 5.0) -> Tuple[Optional[dict], Optional[str]]:
    """Exec generated code and call skill_impl(cap, ctx). Returns (result, error)."""
    sandbox_globals: Dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    sandbox_locals: Dict[str, Any] = {}
    try:
        exec(compile(code, "<forged_skill>", "exec"), sandbox_globals, sandbox_locals)
    except Exception as e:
        return None, f"compile/define error: {e}"
    fn = sandbox_locals.get(REQUIRED_FUNC_NAME)
    if not callable(fn):
        return None, f"{REQUIRED_FUNC_NAME} not defined after exec"
    result_box: Dict[str, Any] = {}

    def _run():
        try:
            result_box["value"] = fn(cap, copy.deepcopy(ctx))
        except Exception as e:
            result_box["error"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        return None, f"timeout after {timeout_s}s (thread abandoned, not killed)"
    if "error" in result_box:
        return None, result_box["error"]
    return result_box.get("value"), None


# --------------------------------------------------------------- prompting

_SYSTEM_PROMPT = """You write ONE Python function for a WoW-like game agent.

Contract (must follow EXACTLY, this is machine-checked before execution):
- Output ONLY a single top-level function: def skill_impl(cap, ctx):
- No imports, no classes, no exec/eval, no file/network/os/sys access.
- `cap` is a QuestCapability object with ONLY these methods available:
    cap.find_active_quest() -> dict | None
    cap.find_ready_quest() -> dict | None
    cap.find_available_quest_npc() -> dict | None
    cap.get_objectives(q) -> list
    cap.incomplete_objective(q) -> dict | None
    cap.quest_status(q) -> str
    cap.check_progress(q) -> dict
    cap.accept(qid) -> str   # 'SUCCESS' | 'FAILURE'
    cap.navigate_to_turn_in(q) -> str
    cap.turn_in(q) -> str
- `ctx` is a read-only dict snapshot of world_state (hp_frac, has_mob, quest,
  nearby entities, etc — whatever keys the task description lists).
- Return a plain dict describing what you did, e.g. {"action": "accept", "quest_id": "q_x"}
- Keep it short and deterministic. No infinite loops, no sleeps.

You will be told the goal, the available context keys, and (on retries) the
exact error or verifier feedback from the previous attempt. Fix only what is
needed to address that feedback.
"""


def _build_user_prompt(gap: SkillGap, previous: Optional[ForgeAttempt]) -> str:
    lines = [
        f"GOAL: {gap.goal}",
        f"DESCRIPTION: {gap.description}",
        f"AVAILABLE CONTEXT KEYS: {', '.join(gap.context_keys) or '(none specified)'}",
    ]
    if gap.example_failure:
        lines.append(f"RECENT FAILURE TRACE:\n{gap.example_failure}")
    if previous is not None:
        lines.append("--- PREVIOUS ATTEMPT ---")
        lines.append(previous.code)
        if previous.static_error:
            lines.append(f"REJECTED BY SAFETY CHECK: {previous.static_error}")
        elif previous.exec_error:
            lines.append(f"RUNTIME ERROR: {previous.exec_error}")
        elif previous.verifier_verdict:
            lines.append(f"VERIFIER VERDICT: {previous.verifier_verdict} (need 'success')")
        lines.append("Fix the code above to address this feedback. Output ONLY the corrected function.")
    return "\n\n".join(lines)


def _extract_code(llm_text: str) -> str:
    """LLMs love markdown fences even when told not to. Strip them if present."""
    text = llm_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


# ------------------------------------------------------------------ forger


class SkillForge:
    def __init__(
        self,
        library: SkillLibrary,
        llm: Optional[_AnthropicClient] = None,
        max_attempts: int = 3,
        exec_timeout_s: float = 5.0,
    ):
        self.library = library
        self.llm = llm or _AnthropicClient()
        self.max_attempts = max_attempts
        self.exec_timeout_s = exec_timeout_s

    def forge_skill(
        self,
        gap: SkillGap,
        cap: Any,
        ctx: dict,
        verifier: Callable[[dict], str],
        snapshot_fn: Callable[[], dict],
    ) -> ForgeResult:
        """Iteratively propose -> safety-check -> execute -> verify -> refine."""
        attempts: List[ForgeAttempt] = []
        previous: Optional[ForgeAttempt] = None
        for i in range(1, self.max_attempts + 1):
            user_prompt = _build_user_prompt(gap, previous)
            try:
                raw = self.llm.complete(_SYSTEM_PROMPT, user_prompt)
            except LLMCallError as e:
                attempt = ForgeAttempt(attempt_no=i, code="", exec_error=str(e))
                attempts.append(attempt)
                break
            code = _extract_code(raw)
            attempt = ForgeAttempt(attempt_no=i, code=code)

            static_err = _static_safety_check(code)
            if static_err:
                attempt.static_error = static_err
                attempts.append(attempt)
                previous = attempt
                continue

            before = snapshot_fn()
            _, exec_err = _execute_sandboxed(code, cap, ctx, timeout_s=self.exec_timeout_s)
            if exec_err:
                attempt.exec_error = exec_err
                attempts.append(attempt)
                previous = attempt
                continue

            after = snapshot_fn()
            verdict = verifier({"before": before, "after": after, "handle": None})
            attempt.verifier_verdict = verdict
            attempts.append(attempt)

            if verdict == "success":
                attempt.accepted = True
                skill_id = f"forged_{gap.goal}"
                skill = Skill(
                    skill_id=skill_id,
                    name=gap.goal,
                    description=gap.description,
                    category="forged",
                    implementation=code,
                )
                skill.record_success()
                added = self.library.add(skill)
                if not added:
                    existing = self.library.get(skill_id)
                    existing.implementation = code
                    existing.record_success()
                    self.library.save()
                return ForgeResult(
                    goal=gap.goal, accepted=True, attempts=attempts, final_skill_id=skill_id
                )
            previous = attempt

        return ForgeResult(goal=gap.goal, accepted=False, attempts=attempts, final_skill_id=None)


# ------------------------------------------------------------------ wiring note
#
# Intended call site (NOT wired here — that's a separate, reviewable change):
#
#   curriculum.py should grow a `maybe_request_skill_gap(stats) -> Optional[SkillGap]`
#   that fires only after repeated (e.g. >=5) failures of the same objective
#   type with no existing skill_library entry covering it — this keeps
#   forge_skill() out of the per-tick hot loop, matching the LLM-advisory rule
#   in this project (WOC_BRAIN=off style periodic gating), same as any other
#   LLM call in this codebase.
