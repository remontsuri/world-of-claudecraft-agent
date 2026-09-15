#!/usr/bin/env python3
"""test_obs_layout.py — раскладка obs не должна зависеть от версии игры.

Проверяем на синтетической obs обеих версий (48 слотов/607 и 28/567):
  1) obs_layout.detect даёт верные границы блоков;
  2) quest_oracle.quest_slots читает состояние квеста именно из квестового блока;
  3) fly_brain.extract_features_v1/v2 не падают и видят интеракт/квест;
  4) значения v1/v2 на 607 совпадают с формулой старой (захардкоженной) раскладки —
     то есть фикс ничего не сломал на прежней версии игры.

Запуск:  python3 tools/test_obs_layout.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obs_layout import detect                       # noqa: E402
from quest_oracle import quest_slots, load_table    # noqa: E402
from fly_brain import extract_features_v1, extract_features_v2  # noqa: E402

CASES = [  # (obs_size, ability_slots, старые индексы: target, mobs, interact, quest)
    (607, 48, (112, 121, 151, 156)),
    (567, 28, (72, 81, 111, 116)),
]


def synth(obs_size: int, layout, n_quests: int) -> np.ndarray:
    """obs с известными значениями в ключевых блоках."""
    o = np.zeros(obs_size, dtype=np.float32)
    o[4], o[5] = 0.1, -0.05          # x, z
    o[6], o[7] = 0.0, 1.0            # facing -> 0 рад
    o[8] = 0.5                       # GCD тикает
    o[0], o[1], o[11] = 0.8, 0.6, 1.0
    o[layout.ability_base: layout.target_base: 2] = 1.0     # способности готовы
    o[layout.target_base] = 1.0                             # цель есть
    o[layout.target_base + 1] = 0.9                         # hp цели
    o[layout.target_base + 3] = 0.6                         # дистанция (d/40)
    o[layout.target_base + 4] = 0.5                         # пеленг sin
    o[layout.target_base + 5] = -0.5                        # пеленг cos
    o[layout.mobs_base] = 0.5                               # ближайший моб
    o[layout.mobs_base + 1], o[layout.mobs_base + 2] = 0.3, 0.9
    o[layout.mobs_base + 5: layout.interact_base: 6] = 1.0  # флаги агро
    o[layout.interact_base] = 1.0                           # интеракт есть
    o[layout.interact_base + 1] = 0.15                      # d/40 -> близко
    o[layout.quest_base] = 0.66                             # первый квест: сдавать
    o[layout.quest_base + 1] = 0.5                          # прогресс
    o[layout.quest_base + 2] = 0.33                         # второй: активен
    o[layout.quest_base + 3] = 0.25
    return o


def main() -> int:
    table = load_table()
    ok = True
    for obs_size, abilities, old_idx in CASES:
        L = detect(obs_size, len(table["order"]))
        got = (L.target_base, L.mobs_base, L.interact_base, L.quest_base)
        good = L.ability_slots == abilities and got == old_idx
        ok &= good
        print(f"{'OK ' if good else 'FAIL'} {L.describe()}")
        if not good:
            print(f"      ожидалось slots={abilities} блоки={old_idx}, получено {got}")

        o = synth(obs_size, L, len(table["order"]))
        slots = quest_slots(o, table)
        q0 = slots[0]
        good = q0[1] == "ready" and abs(q0[2] - 0.5) < 1e-6 and slots[1][1] == "active"
        ok &= good
        print(f"{'OK ' if good else 'FAIL'} quest_slots: {q0[0]} -> {q0[1]} прогресс {q0[2]}; "
              f"{slots[1][0]} -> {slots[1][1]}")

        for name, fn in (("v1", extract_features_v1), ("v2", extract_features_v2)):
            f = fn(o)
            issues = []
            if f.shape != (13,):
                issues.append(f"форма {f.shape}")
            if not np.isfinite(f).all():
                issues.append("не-числа")
            if name == "v2":
                if f[11] <= 0.5:
                    issues.append(f"interact_prox={f[11]:.3f} (ждали >0.5)")
                if abs(f[12] - 1.0) > 1e-6:
                    issues.append(f"quest_signal={f[12]:.3f} (ждали 1.0 = 'сдавать')")
            good = not issues
            ok &= good
            print(f"{'OK ' if good else 'FAIL'} {name}: {np.round(f, 3).tolist()}"
                  + (" | " + "; ".join(issues) if issues else ""))

        # на 607 v1/v2 обязаны совпасть со старой формулой (те же индексы, что были)
        if obs_size == 607:
            f1, f2 = extract_features_v1(o), extract_features_v2(o)
            exp1_quest = o[157:604:2].mean()
            exp2_interact = float(o[151]) * (1.0 - min(o[152] / 1.5, 1.0))
            good = abs(f1[12] - exp1_quest) < 1e-6 and abs(f2[11] - exp2_interact) < 1e-6
            ok &= good
            print(f"{'OK ' if good else 'FAIL'} регрессия 607: старые индексные формулы "
                  f"совпали (quest {f1[12]:.3f}, interact {f2[11]:.3f})")
    print("\nитог:", "все проверки прошли" if ok else "есть провалы")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
