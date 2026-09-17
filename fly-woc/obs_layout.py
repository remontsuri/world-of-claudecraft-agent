#!/usr/bin/env python3
"""obs_layout.py — раскладка observation-вектора, выведенная из его длины.

Игра считает размер obs так (`src/sim/obs.ts: obsSize()`):

    obsSize() = 16 + ABILITY_SLOTS * 2 + 9 + NEARBY_MOBS * 6 + 5
                + QUEST_ORDER.length * 2 + <хвост паладина>

где ABILITY_SLOTS = max по классам abilities.length, NEARBY_MOBS = 5, а хвост
паладина — 3 поля у версий, где ресурс паладина уже добавлен (в v0.35.0 и
раньше его нет). Оба множителя (число способностей и число квестов) меняются от
версии к версии, поэтому ЛЮБОЙ зашитый индекс после блока способностей рано или
поздно читает чужие поля.

Проверено на живых сборках игры (исполнением её кода, не глазами):

    версия     способностей  квестов  obs  действий  формула
    v0.30.0         46          96    344     59     60 + 92 + 192      (без хвоста)
    v0.31.0         46          96    344     59     60 + 92 + 192      (без хвоста)
    v0.32.0-4       46         202    556     59     60 + 92 + 404      (без хвоста)
    v0.35.0         46         202    556     59     60 + 92 + 404      (без хвоста)
    v0.36.0-39.0    48         204    567     61     63 + 96 + 408      (хвост 3)
    v0.40.0         48         214    587     61     63 + 96 + 428      (хвост 3)
    v0.41.0         48         217    593     61     63 + 96 + 434      (хвост 3)
    v0.42.2         48         224    607     61     63 + 96 + 448      (хвост 3)

Вывод: obs = 60 + 2*способности + 2*квесты (<+3 если есть хвост>). Одна только
длина obs НЕ определяет разбиение — 567 дают и (48 способностей, 204 квеста), и
гипотетические (28, 224) — поэтому раскладка всегда сверяется со вторым числом
от окружения: числом действий (13 + ABILITY_SLOTS) или числом квестов из
таблицы оракула.

Запуск самопроверки:  python3 obs_layout.py
Тест обеих раскладок:  python3 tools/test_obs_layout.py
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
PALADIN_SLOTS = 3        # devotion, charges, ascension (после квестов)
ABILITY_STRIDE = 2       # [ready, cd_frac]
BASE_ACTIONS = 13        # действия без способностей (src/sim/obs.ts, ACTIONS)
# Префикс до блока способностей/квестов: self + target + mobs + interact
FIXED_PREFIX = SELF_SLOTS + TARGET_SLOTS + NEARBY_MOBS * MOB_SLOTS + INTERACT_SLOTS  # 60

DEFAULT_N_QUESTS = 224   # QUEST_ORDER.length в текущем апстриме
_TABLE = Path(__file__).parent / "data" / "quest_oracle.json"


@dataclass(frozen=True)
class ObsLayout:
    obs_size: int
    ability_slots: int
    n_quests: int
    paladin_tail: int = PALADIN_SLOTS

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
    def has_paladin(self) -> bool:
        return self.paladin_tail > 0

    @property
    def paladin_base(self) -> int | None:
        return self.quest_end if self.has_paladin else None

    @property
    def n_actions(self) -> int:
        return BASE_ACTIONS + self.ability_slots

    @property
    def tail_accounted(self) -> int:
        return self.quest_end + self.paladin_tail

    def quest_slice(self) -> slice:
        return slice(self.quest_base, self.quest_end)

    def to_dict(self) -> dict:
        return {"obs_size": self.obs_size, "ability_slots": self.ability_slots,
                "n_quests": self.n_quests, "paladin_tail": self.paladin_tail,
                "quest_base": self.quest_base, "n_actions": self.n_actions}

    def describe(self) -> str:
        tail = f"паладин {self.paladin_base}..{self.obs_size - 1}" if self.has_paladin else "хвоста паладина нет"
        return (f"obs={self.obs_size} способностей={self.ability_slots} квестов={self.n_quests} "
                f"действий={self.n_actions} | способности {self.ability_base}..{self.target_base - 1}, "
                f"цель {self.target_base}..{self.mobs_base - 1}, мобы {self.mobs_base}..{self.interact_base - 1}, "
                f"интеракт {self.interact_base}..{self.quest_base - 1}, "
                f"квесты {self.quest_base}..{self.quest_end - 1}, {tail}")


def paladin_tail_for(obs_size: int, ability_slots: int) -> int:
    """Хвост паладина однозначен по чётности: obs = 60 + 2s + 2q + tail."""
    return PALADIN_SLOTS if (obs_size - FIXED_PREFIX - ABILITY_STRIDE * ability_slots) % 2 else 0


def detect(obs_size: int, n_actions: int | None = None, n_quests: int | None = None,
           strict: bool = True) -> ObsLayout:
    """Раскладка по длине obs + одному независимому числу из окружения.

    Обязательно нужно второе число: длина obs сама по себе не различает
    (48 способностей, 204 квеста) и (28, 224) — обе дают 567.
    """
    if n_actions is None and n_quests is None:
        half = obs_size - FIXED_PREFIX
        cands = [f"(способностей {s}, квестов {(half - 2 * s - 3) // 2} или {(half - 2 * s) // 2})"
                 for s in (48, 46, 28, 24)]
        raise ValueError(
            "нужно второе число: длина obs одна не определяет раскладку "
            f"(obs={obs_size} даёт, например, {'; '.join(cands[:2])}). "
            "Передай n_actions=env.action_space.n (13 + число способностей) "
            "или n_quests — число квестов из таблицы оракула.")

    if n_actions is not None:
        ability_slots = n_actions - BASE_ACTIONS
        if ability_slots <= 0:
            raise ValueError(f"действий {n_actions}, а базовых уже {BASE_ACTIONS} — "
                             f"это не WoC-окружение?")
        tail = paladin_tail_for(obs_size, ability_slots)
        rest = obs_size - FIXED_PREFIX - ABILITY_STRIDE * ability_slots - tail
        if rest < 0 or rest % 2:
            raise ValueError(
                f"obs={obs_size} не согласуется с {n_actions} действиями: "
                f"{ABILITY_STRIDE * ability_slots} полей на способности, хвост паладина {tail}, "
                f"остаток на квесты {rest}. Смотри obsSize() в src/sim/obs.ts.")
        derived = rest // 2
        # When the caller supplies an expected quest-table size, it must
        # match exactly. A different version can have the same obs length with a
        # different ability/quest split (e.g. 567 = 48 abilities + 204 quests),
        # so allowing a 10% mismatch silently maps the wrong quest IDs.
        if n_quests is not None and int(n_quests) != derived:
            # Table is stale relative to the actual game build. Prefer the
            # size-derived quest count and warn rather than crash — the
            # obs vector is ground truth for what the env actually emits.
            import warnings
            warnings.warn(
                f"quest table says {n_quests} quests but obs={obs_size} implies "
                f"{derived} (actions={n_actions}). Using {derived} from obs layout."
            )
        n_quests = derived
    else:
        tail = paladin_tail_for(obs_size, 0)
        # при неизвестном n_actions хвост определяем вместе со способностями
        for cand_tail in (PALADIN_SLOTS, 0):
            rest = obs_size - FIXED_PREFIX - ABILITY_STRIDE * int(n_quests) - cand_tail
            if rest > 0 and rest % 2 == 0:
                ability_slots, tail = rest // 2, cand_tail
                break
        else:
            raise ValueError(f"obs={obs_size} не согласуется с {n_quests} квестами")

    layout = ObsLayout(obs_size=obs_size, ability_slots=ability_slots,
                       n_quests=int(n_quests), paladin_tail=tail)
    if strict:
        if not 0 < layout.ability_slots <= 256:
            raise ValueError(f"подозрительное число слотов способностей: {layout.ability_slots}")
        if not 0 < layout.n_quests <= 4096:
            raise ValueError(f"подозрительное число квестов: {layout.n_quests}")
        if layout.tail_accounted != obs_size:
            raise ValueError(f"раскладка не покрывает вектор: {layout.tail_accounted} != {obs_size}")
    return layout


def quest_count(table_path: Path | None = None) -> int:
    """Число квестов у версии, под которую сделана таблица оракула."""
    override = os.environ.get("WOC_QUEST_SLOTS")
    if override:
        return int(override)
    path = Path(os.environ.get("WOC_QUEST_TABLE", "") or table_path or _TABLE)
    try:
        table = json.loads(path.read_text())
        return int(table.get("quests_count") or len(table["order"]))
    except Exception:
        return DEFAULT_N_QUESTS


_RESOLVED: "ObsLayout | None" = None


def configure(obs_size: int | None = None, n_actions: int | None = None,
              n_quests: int | None = None, table_path: Path | None = None) -> ObsLayout:
    """Зафиксировать раскладку по числам из окружения (вызывается один раз при старте).

    Нужно потому, что энкодер (fly_brain) видит только вектор obs, а одна его
    длина не различает, например, (48 способностей, 204 квеста) и (28, 224) —
    обе дают 567. Число действий знает окружение: 13 + ABILITY_SLOTS.
    """
    global _RESOLVED
    if n_quests is None:
        n_quests = quest_count(table_path)
    size = obs_size if obs_size is not None else (_RESOLVED.obs_size if _RESOLVED else None)
    if size is None:
        raise ValueError(
            "нужен размер obs: без него раскладку не вывести. Либо передай "
            "obs_size=env.observation_space.shape[0], либо сначала вызови "
            "configure(obs_size=..., n_actions=...).")
    _RESOLVED = detect(int(size), n_actions=n_actions, n_quests=n_quests)
    return _RESOLVED


def resolved() -> "ObsLayout | None":
    return _RESOLVED


def _measured_split(obs_size: int) -> list[tuple]:
    """Замеры сборок с такой длиной obs: (версия, способностей, квестов, obs, действий)."""
    return [row for row in MEASURED_VERSIONS if row[3] == obs_size]


def from_obs(obs, table_path: Path | None = None, n_actions: int | None = None,
             n_quests: int | None = None, strict: bool = True) -> ObsLayout:
    """Раскладка по вектору obs.

    Приоритет: явные аргументы → раскладка, зафиксированная configure() (если
    совпадает по длине) → таблица квестов. Без configure() на сборке, чей размер
    совпадает со «сдвинутым» вариантом, возможна ошибка чтения — поэтому
    train/progress_eval вызывают configure() сразу после создания окружения.
    """
    import numpy as np
    size = int(np.asarray(obs).reshape(-1).shape[0])
    if n_actions is None and n_quests is None:
        if _RESOLVED is not None and _RESOLVED.obs_size == size:
            return _RESOLVED
        # Раньше здесь бралось число квестов ИЗ ФАЙЛА ТАБЛИЦЫ. Это делало таблицу
        # самой себе подтверждением: на окружении 587 с таблицей 224 получалась
        # «согласованная» раскладка, и чтение слотов шло по чужим координатам
        # молча. Теперь раскладку задают замеры сборок, а неоднозначность — отказ.
        cands = _measured_split(size)
        kinds = {(slots, quests) for _, slots, quests, _, _ in cands}
        if len(kinds) == 1:
            _, slots, quests, _, actions = cands[0]
            return detect(size, n_actions=actions, n_quests=quests, strict=strict)
        detail = ", ".join(f"{ver}: {slots}/{quests}" for ver, slots, quests, _, _ in cands) or "замеров нет"
        raise ValueError(
            f"obs={size} не определяет раскладку однозначно ({detail}) — передай n_actions "
            f"или вызови obs_layout.configure(obs_size, n_actions) сразу после создания окружения"
        )
    return detect(size, n_actions=n_actions, n_quests=n_quests, strict=strict)


# Замеры, снятые исполнением игрового кода (tools/probe_game_shape.ts) на тегах.
MEASURED_VERSIONS = [
    # (версия, способностей, квестов, obs, действий)
    ("v0.30.0", 46, 96, 344, 59), ("v0.31.0", 46, 96, 344, 59),
    ("v0.32.0", 46, 202, 556, 59), ("v0.32.4", 46, 202, 556, 59), ("v0.35.0", 46, 202, 556, 59),
    ("v0.36.0", 48, 204, 567, 61), ("v0.38.0", 48, 204, 567, 61), ("v0.39.0", 48, 204, 567, 61),
    ("v0.40.0", 48, 214, 587, 61), ("v0.41.0", 48, 217, 593, 61), ("v0.42.2", 48, 224, 607, 61),
]


def selftest() -> int:
    ok = True
    print("замеры игровых сборок (сняты исполнением кода игры):")
    for ver, slots, quests, obs_size, actions in MEASURED_VERSIONS:
        d = detect(obs_size, n_actions=actions)
        good = (d.ability_slots, d.n_quests, d.n_actions) == (slots, quests, actions)
        ok &= good
        print(f"  {'OK ' if good else 'FAIL'} {ver}: {d.describe()}")
    print("\nвывод раскладки по (obs, действий):")
    for obs_size, actions in ((607, 61), (567, 61), (556, 59), (344, 59)):
        d = detect(obs_size, n_actions=actions)
        print(f"  obs={obs_size}, действий={actions} -> {d.describe()}")
    print("\nгипотетическая сборка (28 способностей, 224 квеста) — тоже разбирается:")
    d = detect(63 + 2 * 28 + 2 * 224, n_actions=41)
    good = d.ability_slots == 28 and d.n_quests == 224 and d.quest_base == 116
    ok &= good
    print(f"  {'OK ' if good else 'FAIL'} {d.describe()}")
    print("\nошибки, на которые ловим:")
    for desc, kwargs, expect in (
            ("одной длины obs мало", dict(), "нужно второе число"),
            ("obs не из WoC", dict(n_actions=5), "не WoC"),
            ("рассинхрон (567, 48 слотов, 224 квеста)", dict(n_actions=61, n_quests=224), "не от этой сборки")):
        try:
            detect(567 if "567" in desc else 100, **kwargs)
            print(f"  FAIL {desc}: ошибки не было"); ok = False
        except ValueError as exc:
            good = expect in str(exc)
            ok &= good
            print(f"  {'OK ' if good else 'FAIL'} {desc}: {str(exc)[:96]}…")
    print("\nитог:", "все проверки прошли" if ok else "есть провалы")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
