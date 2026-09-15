#!/usr/bin/env python3
"""obs_layout.py — раскладка observation-вектора, выведенная из его длины.

Игра считает размер obs формулой (`src/sim/obs.ts`):

    obsSize() = 16 + ABILITY_SLOTS * 2 + 9 + NEARBY_MOBS * 6 + 5
                + QUEST_ORDER.length * 2 + 3

где ABILITY_SLOTS = max по классам abilities.length, а NEARBY_MOBS = 5.
То есть obs = 63 + 2*ABILITY_SLOTS + 2*КВЕСТЫ, и при изменении числа слотов
способностей (48 → 28 в текущей версии игры) ВСЕ блоки после способностей
сдвигаются. Захардкоженный QUEST_BASE = 156 в такой ситуации молча читает
чужие поля или выходит за границы.

Поэтому блоки считаются от конца вектора: хвост (паладин 3 → квесты → интеракт
→ мобы → цель) фиксирован, а способности «впитывают» остаток.

    607 = 63 + 2*48 + 2*224   →  quest_base 156, interact 151, mobs 121
    567 = 63 + 2*28 + 2*224   →  quest_base 116, interact 111, mobs  81

Запуск самопроверки:  python3 obs_layout.py
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SELF_SLOTS = 16          # hp..overpower
TARGET_SLOTS = 9
NEARBY_MOBS = 5
MOB_SLOTS = 6            # на моба: [exists, d/40, sin, cos, hp, aggro]
INTERACT_SLOTS = 5       # [exists, d/40, sin, cos, type]
PALADIN_SLOTS = 3        # devotion, charges, ascension
ABILITY_STRIDE = 2       # [ready, cd_frac]
BASE_ACTIONS = 13        # действия без способностей (src/sim/obs.ts, ACTIONS)
HEAD = SELF_SLOTS + TARGET_SLOTS + NEARBY_MOBS * MOB_SLOTS + INTERACT_SLOTS + PALADIN_SLOTS  # 63

DEFAULT_N_QUESTS = 224   # QUEST_ORDER.length; уточняется из data/quest_oracle.json

_TABLE = Path(__file__).parent / "data" / "quest_oracle.json"


@dataclass(frozen=True)
class ObsLayout:
    obs_size: int
    ability_slots: int
    n_quests: int

    # --- границы блоков ---
    @property
    def ability_base(self) -> int:
        return SELF_SLOTS

    @property
    def target_base(self) -> int:
        return self.ability_base + self.ability_slots * ABILITY_STRIDE

    @property
    def mobs_base(self) -> int:
        return self.target_base + TARGET_SLOTS

    @property
    def interact_base(self) -> int:
        return self.mobs_base + NEARBY_MOBS * MOB_SLOTS

    @property
    def quest_base(self) -> int:
        return self.interact_base + INTERACT_SLOTS

    @property
    def quest_end(self) -> int:
        return self.quest_base + self.n_quests * 2

    @property
    def paladin_base(self) -> int:
        return self.quest_end

    @property
    def quest_span(self) -> int:
        return self.n_quests * 2

    @property
    def n_actions(self) -> int:
        return BASE_ACTIONS + self.ability_slots

    def quest_slice(self) -> slice:
        return slice(self.quest_base, self.quest_end)

    def describe(self) -> str:
        return (f"obs={self.obs_size} способностей={self.ability_slots} "
                f"квестов={self.n_quests} действий={self.n_actions} | "
                f"способности 16..{self.target_base - 1}, цель {self.target_base}"
                f"..{self.mobs_base - 1}, мобы {self.mobs_base}..{self.interact_base - 1}, "
                f"интеракт {self.interact_base}..{self.quest_base - 1}, "
                f"квесты {self.quest_base}..{self.quest_end - 1}, "
                f"паладин {self.paladin_base}..{self.obs_size - 1}")


def detect(obs_size: int, n_quests: int = DEFAULT_N_QUESTS, n_actions: int | None = None,
           strict: bool = True) -> ObsLayout:
    """Раскладка по длине obs. Способности = остаток после фиксированных блоков.

    Одной длины obs мало: (567, 224) и (567, 200) арифметически одинаково
    согласованы (28 слотов против 52). Окружение даёт ещё и размер пространства
    действий (n_actions = 13 + ABILITY_SLOTS), поэтому при наличии n_actions
    сверяем обе величины и падаем внятно, если не сошлось.
    """
    rest = obs_size - HEAD - 2 * n_quests
    if rest < 0:
        raise ValueError(
            f"obs={obs_size} не влезает: фиксированные блоки {HEAD} + 2*{n_quests} квестов "
            f"дают минимум {HEAD + 2 * n_quests}. Проверь число квестов (QUEST_ORDER).")
    if rest % ABILITY_STRIDE:
        raise ValueError(
            f"obs={obs_size} не согласуется с {n_quests} квестами: остаток на способности "
            f"{rest} не делится на {ABILITY_STRIDE}. Игра изменила один из блоков — "
            f"смотри obsSize() в src/sim/obs.ts.")
    layout = ObsLayout(obs_size=obs_size, ability_slots=rest // ABILITY_STRIDE, n_quests=n_quests)
    if strict and not 0 < layout.ability_slots <= 256:
        raise ValueError(f"подозрительное число слотов способностей: {layout.ability_slots}")
    if n_actions is not None and n_actions - BASE_ACTIONS != layout.ability_slots:
        raise ValueError(
            f"obs={obs_size} даёт {layout.ability_slots} слотов способностей, а действий "
            f"{n_actions} (базовых {BASE_ACTIONS}) — то есть "
            f"{n_actions - BASE_ACTIONS}. Не сходится: игре с {n_actions} действиями "
            f"соответствует obs={HEAD + 2 * (n_actions - BASE_ACTIONS) + 2 * n_quests}. "
            f"Вероятно, изменилось число квестов (сейчас берём {n_quests}, "
            f"переопределяется WOC_QUEST_SLOTS).")
    return layout


def quest_count(table_path: Path | None = None) -> int:
    """Число квестов: длина QUEST_ORDER, снятая из data/quest_oracle.json."""
    override = os.environ.get("WOC_QUEST_SLOTS")
    if override:
        return int(override)
    path = Path(table_path or _TABLE)
    try:
        return len(json.loads(path.read_text())["order"])
    except Exception:
        return DEFAULT_N_QUESTS


def from_obs(obs, table_path: Path | None = None, n_actions: int | None = None,
             strict: bool = True) -> ObsLayout:
    """Раскладка по самому вектору obs (его длина + число квестов [+ действий])."""
    import numpy as np
    n = int(np.asarray(obs).reshape(-1).shape[0])
    return detect(n, quest_count(table_path), n_actions=n_actions, strict=strict)


def selftest() -> int:
    cases = [(607, 224, 48, 156), (567, 224, 28, 116)]
    ok = True
    for obs_size, n_quests, abilities, quest_base in cases:
        d = detect(obs_size, n_quests)
        good = (d.ability_slots, d.quest_base, d.interact_base, d.paladin_base) == \
               (abilities, quest_base, quest_base - 5, obs_size - 3)
        ok &= good
        print(f"{'OK ' if good else 'FAIL'} {d.describe()}")
    # будущая раскладка: 32 слота способностей, те же 224 квеста
    d = detect(HEAD + 2 * 32 + 2 * 224, 224)
    good = d.ability_slots == 32 and d.quest_base == 60 + 2 * 32
    ok &= good
    print(f"{'OK ' if good else 'FAIL'} будущая раскладка: {d.describe()}")
    # перекрёстная сверка с числом действий
    d = detect(567, 224, n_actions=41)
    good = d.ability_slots == 28
    ok &= good
    print(f"{'OK ' if good else 'FAIL'} сверка (567, 224, 41 действие) -> {d.ability_slots} слотов")
    try:
        detect(567, 200, n_actions=41)
        print("FAIL рассинхрон квестов не поймали"); ok = False
    except ValueError as exc:
        print(f"OK  рассинхрон ловится: {str(exc)[:88]}...")
    print("итог:", "все проверки прошли" if ok else "есть провалы")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
