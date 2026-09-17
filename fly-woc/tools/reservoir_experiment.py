#!/usr/bin/env python3
"""reservoir_experiment.py — повторяем контроль из научной работы, но в нашей игре.

Что повторяем. В «Flies Are All You Need» (GPF/FLM) сравнили два адаптера с одинаковой
ролью: (а) читает состояния мушиного графа (резервуар), (б) читает вход напрямую, без
графа. Граф повлиял на предсказания, но (б) оказался не хуже. Это честный отрицательный
результат, и его надо воспроизводить у себя, а не принимать на слово.

Постановка. Основная задача — ПРЕДСКАЗАНИЕ СЛЕДУЮЩЕГО СОСТОЯНИЯ (аналог next-token в
LLM): по признакам в момент t предсказать 13 каналов в момент t+1. Сравниваем:
    reservoir : 82 активности DN после шага замороженной схемы   (мозг как подложка)
    direct    : 13 тех же каналов                                (вход без мозга)
    raw       : сырые obs игры                                   (контроль «не выучил ли
                                                                  ридж просто координаты»)
Метод: ridge (закрытая форма), разбиение по времени (учим на первой половине прогона,
проверяем на второй), метрика R² по каждому целевому каналу.

Вторая задача — вектор цели оракула (5 чисел), но только по целям с реальной дисперсией:
у константных целей R² математически взрывается (делим на ~0), такие цели отбрасываются
и это печатается, а не прячется.

Как читать результат честно:
  * reservoir > direct — у нас есть то, чего не нашли авторы FLM; проверять на других сидах;
  * direct >= reservoir — воспроизвели вывод FLM: проводка сама по себе выигрыша не даёт,
    и заявления «коннектом умнее» без такого контроля не стоят ничего.

Запуск (нужна игра; 4000 шагов ≈ 1 минута на CPU):
    WOC_PYTHON_PATH=/home/user/woc-hat/python WOC_QUEST_TABLE=data/quest_oracle.json \
    python3 tools/reservoir_experiment.py --steps 4000 --out outputs/reservoir_experiment.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, os.environ.get("WOC_PYTHON_PATH", "/home/user/woc-hat/python"))

from wow_env import WoWClassicEnv                      # noqa: E402
from obs_layout import configure                       # noqa: E402
from quest_oracle import load_table, oracle_vector     # noqa: E402
from fly_brain import FlyBrain, extract_features       # noqa: E402

VAR_FLOOR = 1e-4        # ниже этого цель считается константой и в R² не идёт


def rollout(steps: int, seed: int, backend: str | None, action_mode: str) -> dict:
    """Собрать на живом прогоне пары (состояние мозга, каналы, obs, след. каналы, цель)."""
    env = WoWClassicEnv(player_class="warrior", max_steps=steps)
    configure(obs_size=env.observation_space.shape[0], n_actions=env.action_space.n)
    table = load_table()
    brain = FlyBrain(backend=backend)
    obs, _ = env.reset(seed=seed)
    brain.reset(1)
    rng = np.random.default_rng(seed)

    dn, ch, raw, goal = [], [], [], []
    for _ in range(steps):
        features = extract_features(obs)
        with torch.no_grad():
            feats = brain.step(torch.as_tensor(features[None]))[0].numpy()
        dn.append(feats.copy())
        ch.append(features.copy())
        raw.append(np.asarray(obs, dtype=np.float32).copy())
        goal.append(oracle_vector(obs, table=table))
        action = (int(rng.integers(0, env.action_space.n)) if action_mode == "random"
                  else int(np.argmax(features)))
        obs, _, term, trunc, _ = env.step(action)
        if term or trunc:
            break
    X = {"dn": np.asarray(dn), "ch": np.asarray(ch), "raw": np.asarray(raw)}
    ch = X["ch"]
    return {"X": {k: v[:-1] for k, v in X.items()},
            "y_next": ch[1:],                       # следующее состояние мира (13 каналов)
            "y_goal": np.asarray(goal)[:-1],        # вектор цели оракула (5 чисел)
            "steps": len(dn)}


def ridge_fit(X: np.ndarray, Y: np.ndarray, lam: float = 1e-2) -> np.ndarray:
    """Закрытая форма ridge-регрессии: (XᵀX + λI)⁻¹XᵀY, с столбцом единиц."""
    Xa = np.concatenate([X, np.ones((X.shape[0], 1), dtype=X.dtype)], axis=1)
    G = Xa.T @ Xa + lam * np.eye(Xa.shape[1], dtype=X.dtype)
    return np.linalg.solve(G, Xa.T @ Y)


def r2_score(Y: np.ndarray, P: np.ndarray, keep: np.ndarray | None = None) -> np.ndarray:
    num = ((Y - P) ** 2).sum(axis=0)
    den = ((Y - Y.mean(axis=0)) ** 2).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r2 = 1.0 - num / np.where(den > VAR_FLOOR * len(Y), den, np.nan)
    if keep is not None:
        r2 = r2[keep]
    return r2


def evaluate(name: str, X: np.ndarray, Y: np.ndarray, split: float,
             keep: np.ndarray | None = None) -> dict:
    n = max(1, int(len(Y) * split))
    W = ridge_fit(X[:n], Y[:n])
    P = np.concatenate([X[n:], np.ones((X.shape[0] - n, 1), dtype=X.dtype)], axis=1) @ W
    r2 = r2_score(Y[n:], P, keep)
    r2 = r2[~np.isnan(r2)]
    return {"name": name, "n_params": int(X.shape[1] * Y.shape[1]),
            "n_targets": int(r2.size), "r2": [round(float(v), 3) for v in r2],
            "r2_mean": round(float(r2.mean()), 3) if r2.size else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=900001)
    ap.add_argument("--backend", default=None, help="scipy | edge | sparse")
    ap.add_argument("--action-mode", default="random", choices=["random", "features"])
    ap.add_argument("--split", type=float, default=0.5, help="доля прогона на обучение")
    ap.add_argument("--out", type=Path, default=HERE / "outputs" / "reservoir_experiment.json")
    args = ap.parse_args()

    t0 = time.perf_counter()
    data = rollout(args.steps, args.seed, args.backend, args.action_mode)
    print(f"собрано {data['steps']} шагов за {time.perf_counter() - t0:.0f} с "
          f"(режим действий: {args.action_mode})")

    print("ЗАДАЧА 1: предсказание следующего состояния мира (13 каналов)")
    res_next = [evaluate(k, data["X"][k], data["y_next"], args.split)
                for k in ("dn", "ch", "raw")]
    for r in res_next:
        print(f"  {r['name']:16s} параметров {r['n_params']:5d} | R² по целям {r['r2']} "
              f"| среднее {r['r2_mean']:+.3f}")

    # Задача 2: вектор цели оракула. Часть целей в произвольном прогоне константна
    # (например «активен?» = 0, когда рядом нет моба) — их R² не определён, отбрасываем.
    Yg = data["y_goal"]
    std = Yg.std(axis=0)
    keep = std > VAR_FLOOR
    names = ["dist_norm", "sin", "cos", "активен?", "готов сдать?"]
    print(f"ЗАДАЧА 2: вектор цели оракула (5 чисел; с ненулевой дисперсией "
          f"{int(keep.sum())} из 5: {[n for n, k in zip(names, keep) if k]})")
    res_goal = [evaluate(k, data["X"][k], Yg, args.split, keep) for k in ("dn", "ch", "raw")]
    for r in res_goal:
        print(f"  {r['name']:16s} параметров {r['n_params']:5d} | R² по целям {r['r2']} "
              f"| среднее {r['r2_mean']:+.3f}")

    def verdict(tag: str, res: list[dict]) -> tuple[str, str]:
        best = max(res, key=lambda r: r["r2_mean"])
        if best["name"] == "dn":
            return best["name"], (f"{tag}: резервуар обыграл прямой вход на "
                                  f"{best['r2_mean'] - max(r['r2_mean'] for r in res if r['name'] == 'ch'):+.3f} "
                                  f"— требует проверки на других сидах")
        return best["name"], (f"{tag}: лучший — {best['name']} ({best['r2_mean']:+.3f}); "
                              f"резервуар не лучше прямого входа — воспроизведён вывод FLM: "
                              f"проводка сама по себе выигрыша не даёт")

    b1, v1 = verdict("следующее состояние", res_next)
    b2, v2 = verdict("цель оракула", res_goal)
    print("ВЫВОД:", v1, "||", v2)

    out = {"steps": data["steps"], "seed": args.seed, "split": args.split,
           "action_mode": args.action_mode,
           "next_state": {"targets": "13 каналов", "results": res_next, "best": b1, "verdict": v1},
           "goal": {"targets": names, "kept": [n for n, k in zip(names, keep) if k],
                    "results": res_goal, "best": b2, "verdict": v2}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"файл: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
