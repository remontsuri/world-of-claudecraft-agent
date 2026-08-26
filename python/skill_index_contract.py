"""skill_index_contract.py — runtime-ассерт «Python SKILLS == индексы моста».

Аудит: один сдвиг (BUY -> index 9 вместо 10) молча превращает BUY в HEAL,
и весь replay после этого испорчен. Это дешёвая проверка, которая ловит
рассинхрон при старте, а не через 5000 шагов испорченного обучения.

Проверяется ТРИ уровня:
  1. Python  — hierarchical_env.SKILLS (единственный источник порядка)
  2. bridge  — комментарии `case N: // <skill>` в src/bridge/actions.cjs
  3. handler — что case N действительно есть в switch (не пропущен)

Запуск как скрипта: python skill_index_contract.py
"""
import io
import os
import re
from typing import Dict, List, Tuple

from hierarchical_env import SKILLS

_BRIDGE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src", "bridge", "actions.cjs")

# Синонимы: в мосте комментарий может называть навык иначе, чем Python.
ALIASES = {
    "sell": "sell_junk",
    "cast_frostbolt": "cast_frostbolt",
    "cast_fireball": "cast_fireball",
}


class SkillIndexMismatch(RuntimeError):
    """Порядок навыков Python и моста разошёлся."""


def parse_bridge_cases(path: str = None) -> Dict[int, str]:
    """{index: skill} из `case N: // skill ...` в actions.cjs."""
    path = path or _BRIDGE
    try:
        src = io.open(path, encoding="utf-8").read()
    except OSError as exc:
        raise SkillIndexMismatch("cannot read bridge actions: %s" % exc)

    out: Dict[int, str] = {}
    for m in re.finditer(r"case\s+(\d+):\s*\{?\s*//\s*([a-z_]+)", src):
        idx, name = int(m.group(1)), m.group(2)
        out.setdefault(idx, ALIASES.get(name, name))
    # case без комментария всё равно существует как handler
    for m in re.finditer(r"case\s+(\d+):", src):
        out.setdefault(int(m.group(1)), None)
    return out


def check() -> Tuple[bool, List[str]]:
    """(ok, список проблем). Не бросает — для отчётов."""
    problems: List[str] = []
    bridge = parse_bridge_cases()

    for idx, skill in enumerate(SKILLS):
        if idx not in bridge:
            problems.append(
                "index %d (%s) has NO handler in the bridge switch" % (idx, skill))
            continue
        named = bridge[idx]
        if named is not None and named != skill:
            problems.append(
                "index %d: python says %r, bridge comment says %r"
                % (idx, skill, named))

    extra = [i for i in bridge if i >= len(SKILLS)]
    if extra:
        problems.append(
            "bridge handles indices %s beyond python SKILLS (len=%d)"
            % (sorted(extra), len(SKILLS)))

    return (not problems), problems


def assert_skill_indices_match() -> None:
    """Падать на старте, а не портить replay молча."""
    ok, problems = check()
    if not ok:
        raise SkillIndexMismatch(
            "python SKILLS and bridge action indices disagree:\n  - "
            + "\n  - ".join(problems))


if __name__ == "__main__":
    ok, problems = check()
    bridge = parse_bridge_cases()
    print("python SKILLS (%d):" % len(SKILLS))
    for i, s in enumerate(SKILLS):
        print("  %2d %-16s bridge: %s" % (i, s, bridge.get(i, "MISSING")))
    if ok:
        print("\nOK: indices match")
    else:
        print("\nMISMATCH:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
