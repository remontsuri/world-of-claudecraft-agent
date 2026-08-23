"""Fix4 regression: reflection hints must EXPIRE.

2026-08-23: spin:turn_in_quest was journaled while turn-in was genuinely
broken; after the navigation fix the hint still suppressed turn_in_quest
forever — the self-learning loop could never re-admit a repaired action.
Conclusions describe PAST behavior, so they must decay: load_reflection_hints
drops journal entries older than HINT_TTL_SECONDS. A fresh reflect() rewrites
a still-true conclusion with a new timestamp, so the loop stays
self-correcting: blocks while behavior is bad, releases when fixed.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from policy import load_reflection_hints


def _journal(tmpdir, entries):
    p = os.path.join(tmpdir, "self_reflection.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"journal": entries}, f)
    return tmpdir


def test_fresh_hint_loaded():
    import tempfile
    td = tempfile.mkdtemp()
    _journal(td, [{"kind": "ACTION_SATURATION", "key": "spin:farm",
                   "detail": "x", "hint": "reduce_weight",
                   "t": time.time() - 60}])  # 1 minute old
    h = load_reflection_hints(td)
    assert "spin:farm" in h


def test_stale_hint_expired():
    import tempfile
    from policy import HINT_TTL_SECONDS
    td = tempfile.mkdtemp()
    _journal(td, [{"kind": "ACTION_SATURATION", "key": "spin:turn_in_quest",
                   "detail": "x", "hint": "reduce_weight",
                   "t": time.time() - (HINT_TTL_SECONDS + 30)}])
    h = load_reflection_hints(td)
    assert "spin:turn_in_quest" not in h, "stale hint still steering policy"


def test_mixed_journal_keeps_only_fresh():
    import tempfile
    from policy import HINT_TTL_SECONDS
    td = tempfile.mkdtemp()
    now = time.time()
    _journal(td, [
        {"kind": "ACTION_SATURATION", "key": "spin:heal", "detail": "x",
         "hint": "reduce_weight", "t": now - (HINT_TTL_SECONDS * 3)},
        {"kind": "DEATH_CLUSTER", "key": "death:5_5", "detail": "x",
         "hint": "avoid_when_low_hp", "t": now - 10},
    ])
    h = load_reflection_hints(td)
    assert "spin:heal" not in h
    assert "death:5_5" in h


def test_entry_without_timestamp_dropped():
    """A hand-written or corrupt entry without t is unusable for TTL -> drop."""
    import tempfile
    td = tempfile.mkdtemp()
    _journal(td, [{"kind": "ACTION_SATURATION", "key": "spin:farm",
                   "detail": "x", "hint": "reduce_weight"}])
    h = load_reflection_hints(td)
    assert "spin:farm" not in h
