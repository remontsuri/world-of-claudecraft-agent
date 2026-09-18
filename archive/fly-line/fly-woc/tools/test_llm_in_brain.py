#!/usr/bin/env python3
"""test_llm_in_brain.py — приёмка двусторонней связки «LLM в мозгу».

Проверяем именно то, чем связка отличается от «LLM над мозгом», и то, что она не
превращается в самообман:

1. ЗАПИСЬ В МОЗГ ЕСТЬ И ОНА ЗАМЕТНА. Разные решения LLM дают разные сдвиги каналов, и
   схема на них отвечает: DN меняется на проценты масштаба, а не на доли процента.
   Порог 3 % взят из измерения: до калибровки было 0.4 % (фиктивная связь).
2. ЧТЕНИЕ МОЗГА ЕСТЬ. Сводка активности DN попадает в состояние кортекса штатным полем
   fly_state и уходит в промпт — то есть LLM действительно «видит» мозг.
3. КАНАЛЫ РЕАЛЬНОСТИ ОГРАНИЧЕНЫ. hp/бой/цель/мобы LLM сдвигает не сильнее ±0.10, иначе
   LLM подменяла бы агенту мир, а не влияла на его вычисление. Каналы задачи (11–12) — ±0.25.
4. РАЗРЫВ СВЯЗИ — СТРОГО НУЛЕВОЙ (контроль из FLM). При disconnected=True сдвиг ровно 0,
   каналы не меняются вовсе, DN совпадают с базой бит-в-бит.
5. КАЛИБРОВКА РАВНОПРАВНА. Интерфейс измеряет dDN/dканал и выставляет амплитуды так,
   чтобы «фронтир»-каналы давали примерно одинаковый вклад; таблица из 13 строк и
   достижимость цели печатаются открыто (в т.ч. «упирается в предел»).
6. ПРОЕКТОР ВОСПРОИЗВОДИМ И ПЕРЕСОБИРАЕМ. Один seed — один интерфейс; другой seed даёт
   другой интерфейс (контроль «проводка произвольна, но связь есть»).
7. СВОДКА ПОЛЕЗНА. Верхние DN по модулю, возбуждение = среднее |DN|, торможение учтено.

Запуск: python3 tools/test_llm_in_brain.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("WOC_LLM", "off")

import numpy as np                                                # noqa: E402
import torch                                                      # noqa: E402

import fly_lm_brain as LB                                         # noqa: E402
import fly_llm as FL                                              # noqa: E402
from fly_brain import FlyBrain, extract_features                  # noqa: E402
from obs_layout import from_obs                                   # noqa: E402

TESTS: list[tuple[str, callable]] = []
TABLE = None


def test(fn: callable) -> callable:
    TESTS.append((fn.__doc__ or fn.__name__, fn))
    return fn


def make_obs() -> np.ndarray:
    """Минимальное наблюдение: hp/resource, позиция, направление, один незакрытый квест."""
    o = np.zeros(607, dtype=np.float32)
    o[0], o[1] = 0.7, 0.9
    o[4], o[5], o[6], o[7] = -0.1, -0.05, 0.0, 1.0
    o[from_obs(o, n_actions=61).quest_base] = 0.33
    return o


def brain_dn(feats: np.ndarray, brain: FlyBrain) -> np.ndarray:
    brain.reset(1)
    with torch.no_grad():
        return brain.step(torch.as_tensor(feats[None]))[0].numpy().copy()


def calibrated_link() -> tuple[LB.LLMInBrain, FlyBrain, np.ndarray, np.ndarray]:
    feats = extract_features(make_obs())
    brain = FlyBrain()
    link = LB.LLMInBrain()
    link.calibrate(brain, feats)
    return link, brain, feats, brain_dn(feats, brain)


GOAL_A = {"quest": "q_prof_intro", "mode": "quest", "go": "objective", "objective_index": 0}
GOAL_B = {"quest": "q_wolves", "mode": "survive", "go": "turnin", "objective_index": 1}


@test
def t_llm_writes_into_brain() -> tuple[bool, str]:
    """Запись в мозг: разные решения LLM -> разные каналы -> заметно разные DN (≥3 %)."""
    link, brain, feats, base = calibrated_link()
    scale = float(np.abs(base).max())
    link.drive_from_goal(GOAL_A)
    da = float(np.abs(brain_dn(link.apply(feats), brain) - base).max()) / scale
    link.drive_from_goal(GOAL_B)
    db = float(np.abs(brain_dn(link.apply(feats), brain) - base).max()) / scale
    same = np.array_equal(link.drive_from_goal(GOAL_A), link.drive_from_goal(GOAL_A))
    ok = da >= 0.03 and db >= 0.03 and same
    return ok, (f"вклад в DN: {da*100:.1f} % (quest) и {db*100:.1f} % (survive) от масштаба, "
                f"повтор детерминирован: {same}")


@test
def t_brain_is_read_by_llm() -> tuple[bool, str]:
    """Чтение мозга: сводка DN попадает в состояние кортекса и в промпт (штатное поле)."""
    st = FL.state_from_obs(make_obs(), table=TABLE)
    d = np.zeros(82, dtype=np.float32)
    d[3], d[17] = 0.8, -0.6
    s = LB.summarize_brain(d, [f"DN{i}" for i in range(82)], ["R"] * 82)
    st.fly_state = s.as_dict()
    prompt = st.prompt()
    ok = (st.as_dict()["fly_state"]["top_dn"][0]["type"] == "DN3"
          and "DN3R=+0.80" in prompt and "DN17R=-0.60" in prompt
          and "мозг:" in prompt)
    return ok, f"строка в промпте: {s.text()[:78]}"


@test
def t_reality_channels_bounded() -> tuple[bool, str]:
    """Каналы реальности 0..10 ограничены ±0.10, каналы задачи 11–12 — ±0.25."""
    link, _, _, _ = calibrated_link()
    goals = [{"quest": q, "mode": m, "go": g, "objective_index": i}
             for q in ("q_a", "q_long_quest_id", "") for m in ("survive", "quest", "earn", "explore")
             for g in ("objective", "giver", "turnin") for i in range(4)]
    D = np.stack([link.drive_from_goal(g) for g in goals])
    worst_reality = float(np.abs(D[:, :11]).max())
    worst_task = float(np.abs(D[:, 11:]).max())
    ok = worst_reality <= 0.10 + 1e-6 and worst_task <= 0.25 + 1e-6 and worst_task > 0
    return ok, (f"макс |сдвиг| по {len(goals)} решениям: реальность {worst_reality:.3f} "
                f"(предел 0.10), задача {worst_task:.3f} (предел 0.25)")


@test
def t_disconnection_is_exactly_zero() -> tuple[bool, str]:
    """Разрыв связи: сдвиг ровно 0, каналы не меняются, DN == базе бит-в-бит (контроль FLM)."""
    feats = extract_features(make_obs())
    brain = FlyBrain()
    base = brain_dn(feats, brain)
    link, _, _, _ = calibrated_link()
    cut = LB.LLMInBrain(disconnected=True)
    cut.calibrate(brain, feats)
    link.drive_from_goal(GOAL_B)
    cut.drive_from_goal(GOAL_B)
    linked = brain_dn(link.apply(feats), brain)
    cutted = brain_dn(cut.apply(feats), brain)
    ok = (cut.report()["drive_norm_max"] == 0.0 and np.array_equal(cut.apply(feats), feats)
          and np.array_equal(base, cutted) and not np.array_equal(base, linked))
    return ok, (f"разрыв: |сдвиг|={cut.report()['drive_norm_max']}, каналы не изменены="
                f"{np.array_equal(cut.apply(feats), feats)}, DN совпали={np.array_equal(base, cutted)}; "
                f"связь: макс |ΔDN|={float(np.abs(base - linked).max()):.4f}")


@test
def t_calibration_is_measured_not_declared() -> tuple[bool, str]:
    """Калибровка измеряет наклон по каждому каналу и честно помечает пределы."""
    link, brain, feats, base = calibrated_link()
    cal = link.projector.calibration
    n_reach = sum(1 for r in cal if r["target_met"])
    # проверяем сам наклон: сдвиг канала на probe обязан дать заявленное ΔDN (в допуске 25 %)
    errs = []
    for r in cal:
        i = LB.FEATURE_NAMES_V2.index(r["channel"])
        f = feats.copy()
        f[i] = float(f[i]) + link.projector.probe
        got = float(np.abs(brain_dn(f, brain) - base).max()) / link.projector.probe
        if r["slope"] > 1e-6:
            errs.append(abs(got - r["slope"]) / r["slope"])
    ok = (len(cal) == 13 and n_reach >= 1 and max(errs) < 0.25
          and abs(sum(r["influence_pct"] for r in cal if r["target_met"]) / max(1, n_reach) - 10.0) < 0.5)
    return ok, (f"строк {len(cal)}, цель 10 % достигают {n_reach} канала(ов), "
                f"макс ошибка наклона {max(errs)*100:.1f} % (допуск 25 %); "
                f"схема глуше всех: {min(cal, key=lambda r: r['slope'])['channel']} "
                f"({min(r['slope'] for r in cal):.4f})")


@test
def t_projector_seeded_and_rebuildable() -> tuple[bool, str]:
    """Проектор воспроизводим по seed и меняется при другом seed (контроль «произвольная проводка»)."""
    s = LB.llm_state_from_goal(GOAL_A)
    a = LB.LLMProjector(seed=1).drive(s)
    b = LB.LLMProjector(seed=1).drive(s)
    c = LB.LLMProjector(seed=2).drive(s)
    return (np.array_equal(a, b) and not np.allclose(a, c),
            f"seed=1 дважды одинаково: {np.array_equal(a, b)}; другой seed даёт другое: "
            f"{not np.allclose(a, c)} (макс |Δ| = {float(np.abs(a - c).max()):.3f})")


@test
def t_summary_math() -> tuple[bool, str]:
    """Сводка: верхние DN по модулю, возбуждение = среднее |DN|, торможение учитывается."""
    d = np.zeros(82, dtype=np.float32)
    d[0], d[5], d[9] = 0.2, -0.9, 0.4
    s = LB.summarize_brain(d, [f"T{i}" for i in range(82)], ["L", "R"] * 41, k=2)
    ok = (s.top[0]["type"] == "T5" and s.top[0]["act"] == -0.9
          and abs(s.arousal - (0.2 + 0.9 + 0.4) / 82) < 1e-6 and s.n_active == 3
          and s.as_dict()["text"].startswith("мозг:"))
    return ok, f"топ={[t['type'] for t in s.top]}, возбуждение={s.arousal:.4f}, активных={s.n_active}"


def main() -> int:
    global TABLE
    import quest_oracle as qo
    TABLE = qo.load_table()
    print("ПРИЁМКА «LLM В МОЗГУ» (двусторонняя связка с замороженным коннектомом)")
    bad = 0
    for label, fn in TESTS:
        try:
            ok, detail = fn()
        except Exception as exc:                                  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"  {'OK  ' if ok else 'FAIL'} {label}\n        {detail}")
        bad += not ok
    print(f"ИТОГ: {len(TESTS) - bad}/{len(TESTS)} пройдено")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
