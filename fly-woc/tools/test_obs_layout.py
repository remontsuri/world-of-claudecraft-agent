#!/usr/bin/env python3
"""test_obs_layout.py — раскладка obs не должна зависеть от версии игры.

Сборки сняты исполнением игрового кода (tools/probe_game_shape.ts) на тегах:
obs = 60 + 2*способности + 2*квесты (+3, если есть хвост паладина).

    v0.30-31: 344 / 59 действий / 46 способностей /  96 квестов (без хвоста)
    v0.32-35: 556 / 59 действий / 46 способностей / 202 квеста  (без хвоста)
    v0.36-39: 567 / 61 действие  / 48 способностей / 204 квеста  (хвост)
    v0.40   : 587 / 61           / 48 / 214
    v0.41   : 593 / 61           / 48 / 217
    v0.42+  : 607 / 61           / 48 / 224

Проверяем: (1) вывод раскладки по (obs, действий) на всех этих сборках;
(2) что quest_slots/энкодеры читают нужные поля на синтетике каждой раскладки;
(3) что рассинхрон таблицы оракула со сборкой ловится, а не портит чтение молча.

Запуск:  python3 tools/test_obs_layout.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import obs_layout  # noqa: E402
from obs_layout import detect, MEASURED_VERSIONS  # noqa: E402
from quest_oracle import quest_slots, load_table  # noqa: E402
from fly_brain import extract_features_v1, extract_features_v2  # noqa: E402

TABLE_224 = load_table(HERE / "data" / "quest_oracle.json")          # текущий апстрим
TABLE_204 = load_table(HERE / "data" / "quest_oracle_204.json")      # v0.36–v0.39.0
TABLE_214 = load_table(HERE / "data" / "quest_oracle_214.json")      # v0.40.0


def synth(layout, table) -> np.ndarray:
    """obs нужной формы с известными значениями в каждом блоке."""
    o = np.zeros(layout.obs_size, dtype=np.float32)
    o[0], o[1], o[11] = 0.8, 0.6, 1.0
    o[4], o[5] = 0.1, -0.05
    o[6], o[7] = 0.0, 1.0
    o[8] = 0.5                                             # GCD тикает
    o[layout.ability_base: layout.target_base: 2] = 1.0    # способности готовы
    o[layout.target_base] = 1.0
    o[layout.target_base + 1] = 0.9
    o[layout.target_base + 3] = 0.6
    o[layout.target_base + 4] = 0.5
    o[layout.target_base + 5] = -0.5
    o[layout.mobs_base] = 0.5
    o[layout.mobs_base + 1], o[layout.mobs_base + 2] = 0.3, 0.9
    o[layout.mobs_base + 5: layout.interact_base: 6] = 1.0  # агро
    o[layout.interact_base] = 1.0
    o[layout.interact_base + 1] = 0.15                      # близко
    o[layout.quest_base] = 0.66                             # первый: сдавать
    o[layout.quest_base + 1] = 0.5
    o[layout.quest_base + 2] = 0.33                         # второй: активен
    o[layout.quest_base + 3] = 0.25
    return o


def main() -> int:
    ok = True

    print("1) вывод раскладки по (obs, действий) — замеры реальных сборок")
    for ver, slots, quests, obs_size, actions in MEASURED_VERSIONS:
        d = detect(obs_size, n_actions=actions)
        good = (d.ability_slots, d.n_quests, d.n_actions) == (slots, quests, actions)
        ok &= good
        print(f"  {'OK ' if good else 'FAIL'} {ver}: obs={obs_size} действий={actions} -> "
              f"способностей={d.ability_slots} квестов={d.n_quests} "
              f"(квесты с {d.quest_base}, {'хвост 3' if d.has_paladin else 'без хвоста'})")

    print("\n2) чтение блоков на синтетике каждой раскладки")
    cases = [("v0.42.2 (224 квеста)", 607, 61, TABLE_224),
             ("v0.40.0 (214 квестов)", 587, 61, TABLE_214),
             ("v0.39.0 (204 квеста)", 567, 61, TABLE_204),
             ("гипотетическая 28 слотов", 567, 41, TABLE_224)]
    for label, obs_size, actions, table in cases:
        layout = obs_layout.configure(obs_size=obs_size, n_actions=actions,
                                      n_quests=len(table["order"]))
        o = synth(layout, table)
        slots = quest_slots(o, table)
        issues = []
        if not (slots[0][1] == "ready" and abs(slots[0][2] - 0.5) < 1e-6):
            issues.append(f"первый квест прочитан как {slots[0][1]}/{slots[0][2]}")
        if slots[1][1] != "active":
            issues.append(f"второй квест прочитан как {slots[1][1]}")
        f1, f2 = extract_features_v1(o), extract_features_v2(o)
        if f1.shape != (13,) or not np.isfinite(f1).all():
            issues.append("v1 плохой")
        if f2.shape != (13,) or not np.isfinite(f2).all():
            issues.append("v2 плохой")
        if f2[11] <= 0.5:
            issues.append(f"interact_prox={f2[11]:.3f}")
        if abs(f2[12] - 1.0) > 1e-6:
            issues.append(f"quest_signal={f2[12]:.3f}")
        good = not issues
        ok &= good
        print(f"  {'OK ' if good else 'FAIL'} {label}: {layout.describe()}"
              + (" | " + "; ".join(issues) if issues else ""))

    print("\n2a) раскладка выводится из замеров сборки, а не из файла таблицы")
    for size, expect_quests in ((587, 214), (607, 224), (567, 204), (556, 202)):
        d = obs_layout.from_obs(np.zeros(size, dtype=np.float32))
        good = d.n_quests == expect_quests
        ok &= good
        print(f"  {'OK ' if good else 'FAIL'} obs={size} без configure() -> квестов={d.n_quests} "
              f"(ожидалось {expect_quests})")

    print("\n3) регрессия: на 607 старые индексные формулы дают то же")
    layout = obs_layout.configure(obs_size=607, n_actions=61, n_quests=224)
    o = synth(layout, TABLE_224)
    f1, f2 = extract_features_v1(o), extract_features_v2(o)
    exp1 = o[157:604:2].mean()
    exp2 = float(o[151]) * (1.0 - min(o[152] / 1.5, 1.0))
    good = abs(f1[12] - exp1) < 1e-6 and abs(f2[11] - exp2) < 1e-6
    ok &= good
    print(f"  {'OK ' if good else 'FAIL'} quest(v1)={f1[12]:.3f}=={exp1:.3f}, "
          f"interact(v2)={f2[11]:.3f}=={exp2:.3f}")

    print("\n4) ошибки, которые обязан ловить")
    for desc, fn, expect in (
            ("одной длины obs мало", lambda: detect(567), "нужно второе число"),
            ("не-WoC окружение", lambda: detect(100, n_actions=5), "не WoC"),
            ("таблица не от этой сборки",
             lambda: detect(567, n_actions=61, n_quests=224), "не от этой сборки"),
            ("чтение слотов из чужой таблицы",
             lambda: quest_slots(synth(obs_layout.configure(obs_size=587, n_actions=61, n_quests=214),
                                       TABLE_224), TABLE_224), "не от этой сборки"),
            ("раскладка неизвестной сборки не угадывается",
             lambda: obs_layout.from_obs(np.zeros(999, dtype=np.float32)), "не определяет раскладку"),
            ("режим «короткая таблица разрешена»",
             lambda: (os.environ.__setitem__("WOC_QUEST_TABLE_ALLOW_SHORT", "1"),
                      quest_slots(synth(obs_layout.configure(obs_size=587, n_actions=61,
                                                             n_quests=214), TABLE_204), TABLE_204)[0],
                      os.environ.pop("WOC_QUEST_TABLE_ALLOW_SHORT"))[1],
             None)):
        try:
            result = fn()
            if expect is None:
                ok &= result is not None
                print(f"  {'OK ' if result is not None else 'FAIL'} {desc}: сработало (первый слот {result})")
            else:
                print(f"  FAIL {desc}: ошибки не было"); ok = False
        except ValueError as exc:
            if expect is None:
                print(f"  FAIL {desc}: неожиданный отказ {str(exc)[:70]}…"); ok = False
            else:
                good = expect in str(exc)
                ok &= good
                print(f"  {'OK ' if good else 'FAIL'} {desc}: {str(exc)[:88]}…")

    print("\nитог:", "все проверки прошли" if ok else "есть провалы")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
