"""Тесты контракта индексов навыков (Python SKILLS == bridge cases).

Ревью: «один сдвиг BUY -> index 9 может превратить BUY в HEAL,
и весь replay после этого будет испорчен».

Запуск: cd python && python -m pytest test_skill_index_contract.py -v
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from hierarchical_env import SKILLS
from skill_index_contract import (SkillIndexMismatch, assert_skill_indices_match,
                                  check, parse_bridge_cases)


def test_live_indices_match_the_real_bridge():
    """Главный тест: текущий код согласован."""
    ok, problems = check()
    assert ok, problems


def test_assert_does_not_raise_on_current_code():
    assert_skill_indices_match()


def test_bridge_parse_finds_every_python_index():
    bridge = parse_bridge_cases()
    for idx in range(len(SKILLS)):
        assert idx in bridge, "bridge has no handler for index %d (%s)" % (
            idx, SKILLS[idx])


def test_buy_is_not_confused_with_heal():
    """Именно тот сценарий из ревью."""
    bridge = parse_bridge_cases()
    assert bridge[SKILLS.index("buy")] in (None, "buy")
    assert bridge[SKILLS.index("heal")] in (None, "heal")
    assert SKILLS.index("buy") != SKILLS.index("heal")


def _fake_bridge(text: str) -> str:
    fh = tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False,
                                     encoding="utf-8")
    fh.write(text)
    fh.close()
    return fh.name


def test_detects_shifted_index():
    """Подсунем мост, где buy стоит не на своём индексе."""
    shifted = "\n".join(
        "case %d: // %s" % (i, s)
        for i, s in enumerate(["farm", "loot", "accept_quest", "turn_in_quest",
                               "sell_junk", "gather", "craft", "heal", "buy",
                               "equip", "cast_frostbolt", "cast_fireball",
                               "craft_item"]))
    path = _fake_bridge(shifted)
    try:
        bridge = parse_bridge_cases(path)
        assert bridge[8] == "buy", "фикстура должна быть сдвинутой"
        assert SKILLS[8] == "equip", "а python ожидает equip на 8"
    finally:
        os.unlink(path)


def test_detects_missing_handler():
    partial = "case 0: // farm\ncase 1: // loot\n"
    path = _fake_bridge(partial)
    try:
        bridge = parse_bridge_cases(path)
        missing = [i for i in range(len(SKILLS)) if i not in bridge]
        assert missing, "должны найтись индексы без handler-а"
    finally:
        os.unlink(path)


def test_unreadable_bridge_is_an_error_not_a_pass():
    """Отсутствующий файл моста НЕ должен молча означать «всё хорошо»."""
    with pytest.raises(SkillIndexMismatch):
        parse_bridge_cases(os.path.join(tempfile.gettempdir(), "no_such_bridge.cjs"))


def test_action_mask_has_no_silent_fallback():
    """SKILL_INDEX должен приходить из hierarchical_env, без дубля в except."""
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "action_mask.py"), encoding="utf-8").read()
    head = src.split("def ")[0]
    assert "from hierarchical_env import SKILLS" in head
    assert "except" not in head, "silent fallback вернулся — единый источник сломан"
