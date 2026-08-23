"""Episodic memory: one jsonl line per attempt (the agent's own experience).

Feeds the LLM brain (llm_brain.py) and any post-mortem: every step appends a
normalized record; readers pull recent attempts / recent failures by quest.
"""
import json
import os
import threading

_LOCK = threading.Lock()


def _norm(rec: dict) -> dict:
    return {
        "t": rec.get("t"), "quest": rec.get("quest"), "step": rec.get("step"),
        "action": rec.get("action"), "result": rec.get("result"),
        "reason": rec.get("reason"), "hp_frac": rec.get("hp_frac"),
        "phase": rec.get("phase"),
    }


class EpisodicLog:
    def __init__(self, path=None):
        self.path = path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "episodic_log.jsonl")

    def append(self, rec: dict):
        line = json.dumps(_norm(rec), ensure_ascii=False)
        with _LOCK:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _load(self):
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    def recent(self, quest_id=None, n=5):
        rows = self._load()
        if quest_id is not None:
            rows = [r for r in rows if r.get("quest") == quest_id]
        return rows[-n:]

    def recent_failures(self, n=3):
        rows = [r for r in self._load() if r.get("result") == "FAILURE"]
        return rows[-n:]
