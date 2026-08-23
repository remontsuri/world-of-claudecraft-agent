"""LLM strategic brain: picks a GOAL from a fixed enum via the local llama-server.

Contract (spec 2026-08-23): the LLM never touches coordinates/keys — it returns
{goal, reason} where goal is one of GOALS, forced server-side by json_schema
strict and re-validated here. Any failure (timeout, garbage, offline) -> None,
and the caller falls back to the plain FSM+Q behavior (zero degradation).
"""
import json
import urllib.request

GOALS = ("ACCEPT", "DO_OBJECTIVE", "RETURN_TO_GIVER",
         "TURN_IN", "SELL_REPAIR", "HEAL", "SURVIVE")

_SCHEMA = {
    "name": "agent_decision", "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "enum": list(GOALS)},
            "reason": {"type": "string"},
        },
        "required": ["goal"], "additionalProperties": False,
    },
}

_SYSTEM = (
    "Стратегический мозг MMO-агента World of ClaudeCraft. Правила выбора цели:\n"
    "- ACCEPT: только квест, которого НЕТ в логе (phase=AVAILABLE)\n"
    "- DO_OBJECTIVE: phase=ACTIVE и progress<required\n"
    "- RETURN_TO_GIVER: progress>=required, но giver далеко (>7yd)\n"
    "- TURN_IN: phase=READY И giver рядом (<7yd)\n"
    "- HEAL: hp_frac<0.35; SURVIVE: dead или hp_frac<0.15\n"
    "- SELL_REPAIR: сумки полны и рядом vendor\n"
    "Учитывай recent_failures: не повторяй недавние проваленные действия.\n"
    "Отвечай только JSON по схеме."
)


class LLMBrain:
    def __init__(self, base_url: str = "http://127.0.0.1:8081", timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def decide(self, world: dict, failures: list, lessons: list):
        """Ask the local LLM for a strategic goal. Returns {goal, reason} or None."""
        body = {
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps(
                    {"world": world, "recent_failures": failures,
                     "lessons": lessons}, ensure_ascii=False)},
            ],
            "temperature": 0.0,
            "max_tokens": 120,
            "response_format": {"type": "json_schema", "json_schema": _SCHEMA},
        }
        req = urllib.request.Request(
            self.base_url + "/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            goal = parsed.get("goal")
            if goal not in GOALS:
                return None
            return {"goal": goal, "reason": str(parsed.get("reason", ""))}
        except Exception:
            return None
