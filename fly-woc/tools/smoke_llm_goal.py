#!/usr/bin/env python3
"""smoke_llm_goal.py — живая проверка «киборга» на настоящей маленькой модели.

Проверяем не рассуждения, а интерфейс: читает ли модель наш промпт, попадает ли
в JSON-схему и укладывается ли ответ в бюджет времени, который есть у игрового
такта (4 решения/с; планировщик вызывается реже такта, ему хватает ~0.3-1.5 с).

Запуск (по умолчанию самая лёгкая модель, чтобы работало и на CPU):
    python3 tools/smoke_llm_goal.py
    python3 tools/smoke_llm_goal.py --model Qwen/Qwen2.5-0.5B-Instruct --reps 3
    python3 tools/smoke_llm_goal.py --no-llm          # только правила (эталон бюджета)

Что печатает: выбранную модель, устройство, время ответа, число токенов, саму цель
и — главное — прошла ли она строгий разбор (fly_llm.parse_goal). Любой промах схемы
виден как фолбэк, а не как «модель вроде ответила».

Модель НЕ обучается и в репозиторий не кладётся: это внешние веса под своими
лицензиями; скрипт только качает их в кэш HF на время запуска.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import numpy as np                                       # noqa: E402

import fly_llm as FL                                     # noqa: E402
import quest_oracle as qo                                # noqa: E402

DEFAULT_MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"


class HFLocalBackend:
    """Локальная модель через transformers. Для GPU: device_map + dtype на карту."""

    def __init__(self, model_id: str, max_new_tokens: int = 96, dtype: str = "auto"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.name = f"hf:{model_id}"
        self.tok = AutoTokenizer.from_pretrained(model_id)
        # На GPU — fp16; на CPU fp32 не влезает в бедную RAM песочницы (2 ГБ),
        # поэтому dim по умолчанию bfloat16 (половина памяти, CPU-ядра это умеют).
        if dtype == "auto":
            dtype = "float16" if torch.cuda.is_available() else "bfloat16"
        kwargs = {"dtype": getattr(torch, dtype), "low_cpu_mem_usage": True}
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device).eval()
        self.max_new_tokens = max_new_tokens
        self.tokens_out = 0

    def complete(self, prompt: str, timeout_s: float, state=None) -> str:
        torch = self.torch
        msgs = [{"role": "user", "content": prompt}]
        text = self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        ids = self.tok(text, return_tensors="pt").to(self.device)
        t0 = time.perf_counter()
        with torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=self.max_new_tokens,
                                      do_sample=False, temperature=None, top_p=None,
                                      pad_token_id=self.tok.eos_token_id)
        self.last_s = time.perf_counter() - t0
        new = out[0][ids["input_ids"].shape[1]:]
        self.tokens_out = int(new.shape[0])
        return self.tok.decode(new, skip_special_tokens=True)


def make_obs() -> np.ndarray:
    """obs=607 с активным первым квестом (та же сборка, что в бенчмарке v2)."""
    from obs_layout import from_obs
    o = np.zeros(607, dtype=np.float32)
    o[0], o[1], o[11] = 0.62, 0.8, 1.0          # hp 62%, ресурс 80%, в бою
    o[4], o[5], o[6], o[7] = -0.05, 0.02, 0.2, 0.98
    L = from_obs(o, n_actions=61)
    o[L.quest_base] = 0.33                       # квест взят, идёт выполнение
    return o


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--no-llm", action="store_true", help="только правила, без модели")
    ap.add_argument("--max-new-tokens", type=int, default=96)
    ap.add_argument("--dtype", default="auto")
    args = ap.parse_args()

    table = qo.load_table()
    obs = make_obs()
    state = FL.state_from_obs(obs, step=1, table=table)
    print(f"состояние: hp={state.hp:.2f} в_бою={state.in_combat} "
          f"квестов_открыто={len(state.open_quests)} первый={state.open_quests[0]['id']}")
    print(f"промпт: {len(state.prompt())} символов")

    if args.no_llm:
        backend: FL.Backend = FL.FakeCortex()
    else:
        print(f"гружу {args.model} ...")
        backend = HFLocalBackend(args.model, args.max_new_tokens, args.dtype)

    loop = FL.CortexLoop(backend, timeout_s=60.0)
    for i in range(args.reps):
        goal = loop.plan(state)
        extra = ""
        if not args.no_llm:
            b = backend
            extra = f" | {b.last_s:.2f}с, {b.tokens_out} токенов"
        print(f"  попытка {i + 1}: источник={goal.source} цель={goal.quest} "
              f"{goal.mode}/{goal.go} причина={goal.reason[:60]!r}{extra}")

    aux, g = FL.aux_for_policy(obs, loop, table) if os.environ.get("WOC_LLM") != "off" \
        else (FL.goal_vector(loop.current(), obs, table), loop.current())
    print("вектор политики:", np.round(aux, 3).tolist(), "| источник:", g.source)
    print("статистика:", json.dumps(loop.stats.summary(), ensure_ascii=False))
    ok = loop.stats.summary()["ok"] >= 1
    print("ИТОГ:", "модель отвечает по схеме" if ok else
          "модель не попадает в схему -> работает фолбэк по правилам")
    return 0 if ok or args.no_llm else 1


if __name__ == "__main__":
    raise SystemExit(main())
