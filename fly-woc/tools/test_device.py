#!/usr/bin/env python3
"""test_device.py — приёмка устройства вычислений: GPU-путь там, где он должен быть.

Проверяем не «есть ли cuda» (в песочнице её нет), а корректность плумбинга:
  1) resolve_device: auto -> лучшее доступное; явный запрос недоступного — ОШИБКА,
     а не тихий откат на CPU (это и был баг: «GPU» в логах при счёте на CPU);
  2) численная эквивалентность бэкендов схемы (scipy / edge / sparse) — GPU-путь
     обязан считать то же самое, что CPU-эталон;
  3) инварианты состояния: выход на self.device, состояние — torch-тензор на
     устройстве (нет скрытого CPU-состояния), silenced/zero_rows/state_copy;
  4) детерминизм шага;
  5) статическая проверка: в torch-ветке step() нет .cpu()/from_numpy;
  6) связка Runner (мозг + readout + маска + оракул) на заглушке окружения;
  7) CLI: у train.py и progress_eval.py есть --device.

Запуск: python3 tools/test_device.py
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import device_utils  # noqa: E402
from device_utils import device_available, resolve_device  # noqa: E402
from fake_wow_env import OBS_SIZE, WoWClassicEnv  # noqa: E402
from fly_brain import FlyBrain  # noqa: E402

PARITY_TOL = 1e-5


def part1_resolve() -> bool:
    ok = True
    dev = resolve_device()
    print(f"  auto -> {dev} (доступно: {device_utils.describe_devices()})")
    ok &= dev.type in ("cpu", "cuda", "mps")
    ok &= str(resolve_device("cpu")) == "cpu"
    if not device_available("cuda"):
        for label, kwargs in (("явный cuda", {}),):
            try:
                resolve_device("cuda", **kwargs)
                print("  FAIL явный запрос cuda при отсутствии GPU не упал"); ok = False
            except RuntimeError as exc:
                print(f"  OK   явный cuda -> ошибка: {str(exc)[:80]}…")
        os.environ["WOC_DEVICE"] = "cuda"
        try:
            resolve_device()
            print("  FAIL WOC_DEVICE=cuda не упал"); ok = False
        except RuntimeError:
            print("  OK   WOC_DEVICE=cuda -> ошибка (без тихого отката)")
        finally:
            os.environ.pop("WOC_DEVICE", None)
        # при strict=False разрешаем запасной путь — он нужен инструментам
        fallback = resolve_device("cuda", strict=False)
        ok &= fallback.type in ("cpu", "mps")
        print(f"  OK   strict=False -> {fallback} (осознанный запасной путь)")
    else:
        print("  GPU есть: проверка отказа пропущена, bench — tools/gpu_check.py")
    return ok


def part2_parity() -> bool:
    torch.manual_seed(0)
    feats = torch.rand(4, 13)
    outs = {}
    for backend in ("scipy", "edge", "sparse"):
        brain = FlyBrain(device="cpu", backend=backend)
        brain.reset(4)
        outs[backend] = brain.step(feats).numpy()
    ok = True
    for name in ("edge", "sparse"):
        d = float(np.abs(outs[name] - outs["scipy"]).max())
        good = d <= PARITY_TOL
        ok &= good
        print(f"  {'OK  ' if good else 'FAIL'} {name} vs scipy: max|Δ| = {d:.2e} (допуск {PARITY_TOL:g})")
    return ok


def part3_invariants() -> bool:
    ok = True
    feats = torch.rand(3, 13)
    for backend in ("edge", "sparse"):
        brain = FlyBrain(device="cpu", backend=backend)
        brain.reset(3)
        out = brain.step(feats)
        good = out.device == brain.device and isinstance(brain.h, torch.Tensor) and brain.h.device == brain.device
        ok &= good
        print(f"  {'OK  ' if good else 'FAIL'} {backend}: out.device={out.device}, состояние torch на {brain.h.device}")
        if not good:
            print("        (скрытое CPU-состояние — ровно тот баг, который вынесли из FlyBrain)")
        brain.step(feats)
        brain.zero_rows([True, False, False])
        z = float(brain.h[0].abs().sum())
        ok &= z == 0.0
        print(f"  {'OK  ' if z == 0 else 'FAIL'} zero_rows(строка 0) -> сумма {z}")
        snap = brain.state_copy()
        brain.step(feats * 0.5)
        brain.restore_state(snap)
        same = bool(torch.equal(brain.h, snap))
        ok &= same
        print(f"  {'OK  ' if same else 'FAIL'} state_copy/restore_state: состояние восстановлено")
        zeros = brain.step(feats, silenced=True)
        ok &= bool((zeros == 0).all()) and zeros.device == brain.device
        print(f"  OK   silenced -> нули на {zeros.device}")
    brain = FlyBrain(device="cpu", backend="scipy")
    brain.reset(2)
    ok &= isinstance(brain.h, np.ndarray)
    print("  OK   scipy: состояние numpy (CPU-эталон по определению)")
    return ok


def part3b_memory() -> bool:
    """Регресс-страж: мозг не должен удерживать полный граф.

    Было: каждая копия FlyBrain держала распарсенный json (1.87M вложенных списков,
    ~0.5 ГБ) — на машине с 1 ГБ два Runner'а падали по OOM, и это выглядело как
    «провал теста устройства». Теперь держим только метаданные и numpy-массивы.
    """
    import gc
    brain = FlyBrain(device="cpu", backend="scipy"); gc.collect()
    biggest = max((len(v) for v in brain.graph.values() if isinstance(v, list)), default=0)
    ok = biggest <= 8835 and set(brain.graph) >= {"n_nodes", "n_edges", "channels", "outputs"}
    retained = sum(len(v) for v in brain.graph.values() if isinstance(v, list))
    print(f"  {'OK  ' if ok else 'FAIL'} метаданные мозга: {len(brain.graph)} полей, список "
          f"самый длинный {biggest} (типы клеток), всего элементов {retained}")
    if not ok:
        print("        в мозге снова оседает полный граф — это ~0.5 ГБ на копию")
    import resource
    print(f"  --   пик RSS процесса: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} МБ")
    del brain; gc.collect()
    return ok


def part4_determinism() -> bool:
    feats = torch.rand(2, 13)
    outs = []
    for _ in range(2):
        brain = FlyBrain(device="cpu", backend="edge")
        brain.reset(2)
        outs.append(brain.step(feats))
    same = bool(torch.equal(outs[0], outs[1]))
    print(f"  {'OK  ' if same else 'FAIL'} одинаковый вход с чистого состояния -> бит-в-бит одинаковый выход")
    return same


def part5_static() -> bool:
    src = inspect.getsource(FlyBrain.step)
    torch_branch = src[src.index("x = feats if isinstance(feats, torch.Tensor)"):]
    bad = [tok for tok in (".cpu()", "from_numpy", "np.asarray", "numpy") if tok in torch_branch]
    ok = not bad
    print(f"  {'OK  ' if ok else 'FAIL'} в torch-ветке step() нет хостовых конверсий" +
          (f" (найдено: {bad})" if bad else ""))
    return ok


def part6_runner() -> bool:
    """Связка Runner на заглушке игры: мозг, readout, маска, оракул — на одном устройстве."""
    stub = types.ModuleType("wow_env")
    stub.WoWClassicEnv = WoWClassicEnv
    sys.modules["wow_env"] = stub
    os.environ.setdefault("WOC_PYTHON_PATH", str(HERE))

    import argparse
    from train import Runner, ability_mask

    args = argparse.Namespace(policy="fly", seed=1, lr=3e-4, oracle_obs=False,
                              mask_abilities=True, ability_idx=WoWClassicEnv().ability_indices)
    runner = Runner(args, 2, OBS_SIZE, 61, device="cpu")
    obs = np.stack([WoWClassicEnv().reset(seed=1)[0] for _ in range(2)])
    feats = runner.feats(obs)
    ok = feats.device == runner.device and next(runner.net.parameters()).device == runner.device
    print(f"  {'OK  ' if ok else 'FAIL'} Runner: feats на {feats.device}, читаут на "
          f"{next(runner.net.parameters()).device}")
    mask = ability_mask(obs, args.ability_idx, 61, device=runner.device)
    print(f"  OK   маска на {mask.device}, запрещено {int((~mask).sum())} действий "
          f"из {mask.numel()} (GCD тикает)")
    actions, logp, value, entropy = runner.act(feats, mask=mask)
    ok &= isinstance(actions, np.ndarray) and logp.device == runner.device and value.device == runner.device
    print(f"  {'OK  ' if ok else 'FAIL'} act: действия numpy (граница со средой), "
          f"logp/value на {logp.device}")
    runner.episode_reset(2)
    runner.reset_done(np.array([True, False]))
    state = runner.brain.h
    # на CPU бэкенд по умолчанию scipy -> состояние numpy (эталон), на GPU — torch
    zeroed = float(np.abs(state[0]).sum() if isinstance(state, np.ndarray) else state[0].abs().sum())
    ok &= zeroed == 0.0
    print(f"  {'OK  ' if zeroed == 0 else 'FAIL'} reset_done обнуляет только сброшенные окружения "
          f"(состояние: {'numpy' if isinstance(state, np.ndarray) else 'torch'} на {runner.device})")

    # Освобождаем первый Runner до сборки второго: на машине с 1 ГБ два мозга разом
    # роняли тест по OOM (и это маскировало настоящие ошибки под «ПРОВАЛ»).
    import gc
    del runner, feats, mask, actions, logp, value, entropy
    gc.collect()

    # оракул-канал: своя таблица (214) работает, чужая (224) обязана отказать
    os.environ["WOC_QUEST_TABLE"] = str(HERE / "data" / "quest_oracle_214.json")
    args2 = argparse.Namespace(policy="fly", seed=1, lr=3e-4, oracle_obs=True,
                               mask_abilities=False, ability_idx=None)
    runner2 = Runner(args2, 2, OBS_SIZE, 61, device="cpu")
    f2 = runner2.feats(obs)
    good = f2.shape[1] == runner2.brain.n_dn + 5
    ok &= good
    print(f"  {'OK  ' if good else 'FAIL'} оракул-канал: feats {tuple(f2.shape)} "
          f"= {runner2.brain.n_dn} DN + 5 (таблица 214)")
    os.environ["WOC_QUEST_TABLE"] = str(HERE / "data" / "quest_oracle.json")
    try:
        Runner(args2, 2, OBS_SIZE, 61, device="cpu")
        print("  FAIL чужая таблица (224) на obs=587 не отказала"); ok = False
    except ValueError:
        print("  OK   чужая таблица (224) на obs=587 -> отказ (гейт работает и в этом пути)")
    finally:
        os.environ.pop("WOC_QUEST_TABLE", None)
    return ok


def part7_cli() -> bool:
    ok = True
    for script in ("train.py", "progress_eval.py"):
        # без чекаута игры train.py не импортируется — подкладываем заглушку из tools/
        res = subprocess.run([sys.executable, str(HERE / script), "--help"],
                             capture_output=True, text=True,
                             env={**os.environ, "WOC_PYTHON_PATH": str(HERE / "tools"),
                                  "PYTHONPATH": str(HERE / "tools")})
        has = "--device" in res.stdout
        ok &= has
        print(f"  {'OK  ' if has else 'FAIL'} {script}: --device {'есть' if has else 'НЕТ'} в --help")
    return ok


def main() -> int:
    ok = True
    for title, fn in (("1) выбор устройства (строгий, без тихого отката)", part1_resolve),
                      ("2) численная эквивалентность бэкендов", part2_parity),
                      ("3) инварианты состояния", part3_invariants),
                      ("3b) память: граф не удерживается", part3b_memory),
                      ("4) детерминизм", part4_determinism),
                      ("5) статическая проверка torch-ветки", part5_static),
                      ("6) связка Runner на заглушке окружения", part6_runner),
                      ("7) CLI", part7_cli)):
        print(title)
        ok &= bool(fn())
    print("\nитог:", "устройство разведено корректно" if ok else "есть провалы")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
