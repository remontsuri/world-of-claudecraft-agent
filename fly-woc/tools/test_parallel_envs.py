#!/usr/bin/env python3
"""test_parallel_envs.py — параллельный шаг по средам: корректность и выигрыш.

Что проверяем и почему именно так:

1. КОРРЕКТНОСТЬ. Параллельный шаг обязан давать ровно те же obs/rewards/dones, что
   и последовательный: потоки ускоряют ожидание среды, а не меняют переходы. Сравнение
   идёт на одинаковых сидах, поэтому расхождение в один элемент — уже ошибка.

2. ВЫИГРЫШ. Заглушка окружения (tools/fake_wow_env.py) с WOC_FAKE_LATENCY_MS = 20
   изображает round-trip к node-процессу. При 8 средах последовательный шаг — это
   8 задержек подряд, параллельный — одна. Ожидание: ускорение близко к числу сред.
   Без задержки мерить нечего: заглушка отвечает мгновенно и упрётся в CPU (это тоже
   проверяется — что WOC_ENV_THREADS=1 остаётся прежним поведением).

Запуск: python3 tools/test_parallel_envs.py
Код возврата 1, если корректность нарушена или выигрыша нет.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("WOC_PYTHON_PATH", str(HERE))          # заглушка wow_env из tools/
os.environ["WOC_FAKE_LATENCY_MS"] = os.environ.get("WOC_FAKE_LATENCY_MS", "20")

import numpy as np                                             # noqa: E402

import train as T                                              # noqa: E402

BATCH = 8
STEPS = 12


def run(threads: int):
    """Прогон EnvBatch с заданным числом потоков. Возвращает (время, трасса)."""
    os.environ["WOC_ENV_THREADS"] = str(threads)
    batch = T.EnvBatch(BATCH, 60, "warrior", rewards=None, args=None)
    log: list = []
    try:
        batch.reset([1000 + i for i in range(BATCH)])
        log.append(np.array(batch.obs, dtype=np.float32))
        rng = np.random.default_rng(3)
        for _ in range(STEPS):
            actions = rng.integers(0, 61, size=BATCH)
            t0 = time.perf_counter()
            dones, rewards = batch.step(actions)
            dt = time.perf_counter() - t0
            log.append((dt, dones.copy(), rewards.copy(), np.array(batch.obs, dtype=np.float32)))
        return batch, log
    finally:
        batch.close()


def main() -> int:
    ok = True
    print(f"=== параллельные среды: {BATCH} сред, {STEPS} шагов, "
          f"задержка заглушки {os.environ['WOC_FAKE_LATENCY_MS']} мс")

    seq_batch, seq = run(1)
    par_batch, par = run(BATCH)

    # --- 1. корректность
    if len(seq) != len(par):
        print("  FAIL трассы разной длины"); ok = False
    else:
        same = np.array_equal(seq[0], par[0])
        print(f"  {'OK  ' if same else 'FAIL'} obs после reset совпадают поэлементно")
        ok &= same
        for i, (a, b) in enumerate(zip(seq[1:], par[1:]), start=1):
            d_done = np.array_equal(a[1], b[1])
            d_rew = np.array_equal(a[2], b[2])
            d_obs = np.array_equal(a[3], b[3])
            if not (d_done and d_rew and d_obs):
                print(f"  FAIL шаг {i}: dones={d_done} rewards={d_rew} obs={d_obs}")
                ok = False
                break
        else:
            print(f"  OK   все {STEPS} шагов: rewards, dones и obs совпадают с последовательным")

    # --- 2. выигрыш
    seq_ms = float(np.median([s[0] for s in seq[1:]])) * 1000
    par_ms = float(np.median([s[0] for s in par[1:]])) * 1000
    speed = seq_ms / par_ms if par_ms else 0.0
    print(f"  медиана шага: последовательно {seq_ms:.1f} мс, в {BATCH} потоков {par_ms:.1f} мс "
          f"→ ускорение {speed:.1f}x (потолок {BATCH}x: ровно столько задержек убрано)")
    if speed < 2.0:
        print("  FAIL ускорения нет — потоки не работают (проверь WOC_ENV_THREADS)")
        ok = False
    else:
        print("  OK   выигрыш есть")

    # --- 3. прежнее поведение выключателя
    if seq_batch.threads != 1:
        print(f"  FAIL WOC_ENV_THREADS=1 дал {seq_batch.threads} потоков"); ok = False
    else:
        print("  OK   WOC_ENV_THREADS=1 — по-прежнему один поток (прежнее поведение)")
    if par_batch.threads != min(BATCH, 16):
        print(f"  FAIL ожидалось {min(BATCH, 16)} потоков, получено {par_batch.threads}"); ok = False
    else:
        print(f"  OK   по умолчанию потоков на среду: {par_batch.threads}")

    print(f"\nИТОГ: {'всё зелёное' if ok else 'ЕСТЬ ОШИБКИ'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
