"""test_replay_persistence.py — regression для 64ea6ad.

Баг: transition с set (напр. keepIds) ронял save() -> весь опыт терялся.
Инвариант: add(transition c set) -> save() -> load() -> количество записей
сохраняется, множества десериализуются как list.
"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(__file__))


def _fresh(path):
    from replay_buffer import ReplayBuffer
    return ReplayBuffer(path=path)


def test_save_load_with_set_survives(tmp_path):
    p = str(tmp_path / "rb.json")
    rb = _fresh(p)
    rb.add({
        "state": "hp=full|qs=ACTIVE",
        "action": "sell_junk",
        "reward": 0.5,
        "next_state": "hp=full|qs=ACTIVE",
        "done": False,
        # множество — именно оно ломало json.dump
        "keepIds": {"ironbark_log", "copper_ore"},
    })
    rb.save()

    rb2 = _fresh(p)  # __init__ вызывает _load()
    n_before = len(rb.buffer)
    assert len(rb2.buffer) == n_before, \
        f"опыт потерян при рестарте: {len(rb2.buffer)} != {n_before}"


def test_save_never_raises_on_exotic_types(tmp_path):
    p = str(tmp_path / "rb2.json")
    rb = _fresh(p)
    rb.add({"state": "s", "action": "buy", "reward": -0.1,
            "next_state": "s", "frozenset_field": frozenset({"a"})})
    # save не должен бросать даже на экзотике (внутри try, но проверяем файл)
    rb.save()
    assert os.path.exists(p), "save() не создал файл"
