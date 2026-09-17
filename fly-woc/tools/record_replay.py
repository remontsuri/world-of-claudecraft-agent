#!/usr/bin/env python3
"""record_replay.py — записать прогон мухи в живой игре, чтобы его можно было УВИДЕТЬ.

Зачем: бенчмарки дают числа (reward, квесты), но не показывают, что агент делает.
Здесь мы гоняем ту же связку, что и в замерах (progress_eval.build: мозг + читаут),
и пишем по каждому шагу всё, что нужно для анимации:

  * мировые координаты (x, z) и курс — из obs по границам мира сборки;
  * выбранное действие (номер и имя);
  * активность 82 нисходящих нейронов (вход читаута) — видно, что «мозг» живой;
  * 13 входных каналов — то, что муха «видит»;
  * ближайшие мобы, интеракт-объект, цель квеста (метка на карте);
  * состояние: hp, уровень, xp, киллы, смерти, сданные квесты, награда.

Запуск:
    export WOC_PYTHON_PATH=/path/to/world-of-claudecraft/python
    python3 tools/record_replay.py --steps 1200 --out replay.json
    python3 tools/render_replay.py replay.json replay.html      # анимация

Опции:
    --stride 2        записывать каждый второй шаг (файл вдвое легче)
    --policy fly-sampled|fly    сэмплировать действия или брать argmax
    --checkpoint outputs/params_fly_v2.pt
    --seed / --torch-seed       те же, что в замерах, иначе эпизод другой
    --stochastic-images? нет.   муха не смотрит картинки — входы 13 каналов
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

from wow_env import WoWClassicEnv                     # noqa: E402
from obs_layout import configure                      # noqa: E402
from quest_oracle import load_table, guidance_from_obs, world_bounds, oracle_vector  # noqa: E402
import fly_llm as FL  # noqa: E402  (LLM-кортекс: он выбирает ЦЕЛЬ, муха рулит)
import fly_lm_brain as LB  # noqa: E402  (двусторонняя связка LLM<->коннектом)
from progress_eval import build                       # noqa: E402
from fly_brain import extract_features, FEATURE_VERSION  # noqa: E402

DEFAULT_REWARDS = {"xp": 0.02, "kill": 1.0, "timePenalty": 0.001,
                   "questProgress": 1.0, "questDone": 10, "levelUp": 5}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", type=int, default=1200)
    ap.add_argument("--stride", type=int, default=2, help="писать каждый N-й шаг")
    ap.add_argument("--policy", default="fly-sampled",
                    choices=["fly", "fly-sampled", "fly-silenced", "fly-untrained", "mlp", "mlp-sampled", "random", "openloop"])
    ap.add_argument("--checkpoint", type=Path, default=HERE / "outputs" / "params_fly_v2.pt")
    ap.add_argument("--seed", type=int, default=900001)
    ap.add_argument("--torch-seed", type=int, default=20260914, dest="torch_seed")
    ap.add_argument("--device", default=None)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--player-class", default="warrior", dest="player_class")
    ap.add_argument("--rewards", default=json.dumps(DEFAULT_REWARDS))
    ap.add_argument("--oracle-obs", action="store_true", dest="oracle_obs",
                    help="боковой канал цели в readout (нужен чек-инт на 87 входов)")
    ap.add_argument("--llm", default="off", choices=["off", "fake", "server"],
                    help="off — как раньше; fake — правила (фолбэк и эталон бюджета); "
                         "server — llama.cpp/Ollama по WOC_LLM_URL")
    ap.add_argument("--llm-period", type=float, default=2.0, dest="llm_period",
                    help="как часто думает кортекс, с; игра идёт 4 решения/с")
    ap.add_argument("--llm-timeout", type=float, default=1.5, dest="llm_timeout")
    ap.add_argument("--llm-couple", default="off", choices=["off", "brain", "brain-cut"],
                    dest="llm_couple",
                    help="off — LLM над мозгом (читает только мир); brain — двусторонняя связка: "
                         "LLM пишет в каналы мозга и читает сводку его активности; "
                         "brain-cut — тот же прогон с РАЗОРВАННОЙ связью (контроль из FLM: "
                         "вклад обязан быть ровно нулевым)")
    ap.add_argument("--couple-probe", type=int, default=0, dest="couple_probe",
                    help="каждые N тактов парно мерить вклад связки: тот же самый h, шаг "
                         "СО сдвигом и БЕЗ него. Пишется в кадр как dnprobe.delta (доля масштаба DN)")
    ap.add_argument("--out", type=Path, default=Path("replay.json"))
    args = ap.parse_args()

    rewards = json.loads(args.rewards) if args.rewards else None
    env = WoWClassicEnv(player_class=args.player_class, max_steps=args.steps, rewards=rewards)
    layout = configure(obs_size=env.observation_space.shape[0], n_actions=env.action_space.n)
    print(f"[obs] {layout.describe()}")
    print(f"[env] obs={env.observation_space.shape[0]} actions={env.action_space.n} "
          f"feature-encoder={FEATURE_VERSION}")

    ckpt = args.checkpoint if args.checkpoint and Path(args.checkpoint).exists() else None
    # Боковой канал цели: +5 входов readout. Его включает либо оракул (база), либо
    # кортекс (киборг). Чек-инт в обоих случаях один и тот же — на 87 входов.
    aux_on = args.llm != "off" or args.oracle_obs
    brain, net = build(args.policy, ckpt, args.torch_seed,
                       env.observation_space.shape[0], env.action_space.n,
                       oracle_extra=5 if aux_on else 0, device=args.device, backend=args.backend)
    if brain is None:
        raise SystemExit("нужен --policy fly* (у mlp/random/openloop нет схемы)")
    print(f"[brain] {brain.describe()}")
    table = load_table()
    minx, maxx, minz, maxz = world_bounds(table)

    obs, info = env.reset(seed=args.seed)
    brain.reset(1)
    rng = np.random.default_rng(args.seed)

    # Двусторонняя связка «LLM в мозгу». Калибровка интерфейса обязательна: без неё
    # проектор писал бы преимущественно в глухие каналы (замер: quest_signal 0.21 %
    # отклика DN против 10 % у resource/target_exists) и связь была бы фиктивной.
    link = None
    if args.llm_couple != "off":
        link = LB.LLMInBrain(disconnected=(args.llm_couple == "brain-cut"))
        cal = link.calibrate(brain, extract_features(obs))
        print(f"[couple] режим={args.llm_couple}, масштаб DN={cal['dn_scale']}, "
              f"вклад каналов: " + ", ".join(f"{r['channel']}={r['influence_pct']}%"
                                             for r in cal["rows"]))
        if link.disconnected:
            print("[couple] контроль: связь РАЗОРВАНА, сдвиг каналов строго нулевой")

    # Кортекс: считает цель в своём потоке и не тормозит такт игры. Пока идёт
    # первый вызов, игра уже шагает с прошлой целью (так и работают все гибриды:
    # медленный планировщик сверху, быстрый реактивный контур снизу).
    cortex = None
    holder = {"obs": np.asarray(obs, dtype=np.float32).copy(), "step": 0, "deaths": 0}
    step_ref = [0]               # текущий такт: нужен внутри policy_feats для --couple-probe
    probe_ref: list[dict] = []   # последнее парное измерение вклада связки (dnprobe)
    if link is not None:         # сюда пишется сводка активности мозга для промпта LLM
        dn_ident = LB.dn_identity()
        holder["fly_state"] = {"top_dn": [], "arousal": 0.0, "n_active": 0, "text": ""}
        holder["dn_types"] = [d["type"] for d in dn_ident]
        holder["dn_sides"] = [d["side"] for d in dn_ident]
    if args.llm != "off":
        cortex = FL.CortexLoop(FL.make_backend(args.llm),
                               period_s=args.llm_period, timeout_s=args.llm_timeout)
        def state_with_brain():
            """Состояние для LLM + сводка активности мозга (LLM читает мозг)."""
            st = FL.state_from_obs(holder["obs"], holder["step"], table,
                                   deaths=holder["deaths"])
            if link is not None:
                st.fly_state = holder["fly_state"]
            return st

        cortex.start(state_with_brain)
        print(f"[llm] кортекс включён: режим={args.llm}, период={args.llm_period}с, "
              f"бэкенд={cortex.backend.name}")
        while cortex.stats.summary()["calls"] == 0:      # дождаться первой цели
            time.sleep(0.01)
    frames: list[dict] = []
    ep_reward = 0.0
    t0 = time.time()
    quests_seen: set[str] = set()

    def policy_feats(o) -> torch.Tensor:
        """DN-активность схемы + боковой канал (оракул или цель кортекса).

        При связке --llm-couple каналы идут в мозг с прибавкой от последнего решения LLM
        (LLM пишет в мозг), а сводка свежей активности DN уходит в состояние кортекса
        (LLM читает мозг) — это и есть двусторонний контур.
        """
        feats = extract_features(o)
        probe = {}
        if link is not None:
            applied = link.apply(feats)
            if (args.couple_probe and step_ref[0] % args.couple_probe == 0
                    and not link.disconnected):
                # Парный контроль на живом такте: мозг рекуррентный, поэтому «что было бы
                # без связки» можно узнать только шагнув второй раз из ТОГО ЖЕ состояния h.
                h_before = brain.state_copy()
                with torch.no_grad():
                    dn_with = brain.step(torch.as_tensor(applied[None]))
                h_after = brain.state_copy()
                brain.restore_state(h_before)
                with torch.no_grad():
                    dn_without = brain.step(torch.as_tensor(feats[None]))
                brain.restore_state(h_after)
                scale = max(1e-9, float(torch.abs(dn_without).max()))
                probe = {"dndelta": float(torch.abs(dn_with - dn_without).max()) / scale,
                         "dnscale": round(scale, 4),
                         "drive_l1": float(np.abs(link.last_drive).sum())}
            feats = applied
        raw = brain.step(torch.as_tensor(feats[None]))
        probe_ref.clear()
        if probe:
            probe_ref.append(probe)
        if link is not None:
            holder["fly_state"] = link.observe_brain(
                raw[0].detach().cpu().numpy(), holder["dn_types"], holder["dn_sides"]
            ).as_dict()
        if not aux_on:
            return raw, None
        if cortex is not None:
            aux, g = FL.aux_for_policy(o, cortex, table, mode=args.llm)
        else:
            aux, g = oracle_vector(o, table=table), None
        raw = torch.cat([raw, torch.as_tensor(aux, dtype=raw.dtype)[None]], dim=-1)
        return raw, g

    for step in range(args.steps):
        step_ref[0] = step
        feats, goal = policy_feats(obs)
        if link is not None and goal is not None:
            # Решение LLM превращается в сдвиг каналов и подействует со следующего такта
            # (в такте рулит коннектом, LLM думает на порядок медленнее — см. CYBORG.md).
            link.drive_from_goal(goal)
        with torch.no_grad():
            logits, _ = net(feats)
        if args.policy.endswith("-sampled"):
            action = int(torch.distributions.Categorical(logits=logits).sample())
        elif args.policy == "random":
            action = int(rng.integers(0, env.action_space.n))
        elif args.policy == "openloop":
            action = 1 if step % 2 == 0 else 9
        else:
            action = int(logits.argmax(-1))
        if args.policy == "fly-silenced":
            feats = brain.step(torch.as_tensor(extract_features(obs)[None]), silenced=True)
            if aux_on:
                feats = torch.cat([feats, torch.as_tensor(
                    (FL.aux_for_policy(obs, cortex, table, mode=args.llm)[0] if cortex is not None
                     else oracle_vector(obs, table=table)), dtype=feats.dtype)[None]], dim=-1)
            with torch.no_grad():
                logits, _ = net(feats)
            action = int(torch.distributions.Categorical(logits=logits).sample())

        # карта: где муха, куда смотрит, что вокруг
        x = float(obs[4]) * maxx
        z = minz + ((float(obs[5]) + 1.0) * 0.5) * (maxz - minz)
        facing = float(np.arctan2(float(obs[6]), float(obs[7])))
        # Метка на карте — от того, кто реально ведёт агента: цель кортекса или оракул
        g = (FL.goal_description(goal, obs, table) if (cortex is not None and goal is not None
             and goal.quest) else None) or guidance_from_obs(obs, table)
        target = g.get("target")
        holder["obs"] = np.asarray(obs, dtype=np.float32).copy()
        holder["step"] = step
        holder["deaths"] = int(info.get("deaths") or 0)
        if g.get("quest"):
            quests_seen.add(str(g["quest"]))

        if step % args.stride == 0:
            mobs = []
            base = layout.mobs_base
            for k in range(5):
                d = float(obs[base + 6 * k]); s = float(obs[base + 6 * k + 1])
                c = float(obs[base + 6 * k + 2]); hp = float(obs[base + 6 * k + 3])
                aggro = float(obs[base + 6 * k + 5])
                if d > 0 or hp > 0:
                    mobs.append([round(d * 40, 1), round(float(np.arctan2(s, c)), 3), round(hp, 2), round(aggro, 1)])
            ib = layout.interact_base
            probe_frame = probe_ref[0] if probe_ref else None
            frames.append({
                "t": step,
                "x": round(x, 1), "z": round(z, 1), "facing": round(facing, 3),
                "a": action, "r": round(ep_reward, 2),
                "hp": round(float(obs[0]), 3), "res": round(float(obs[1]), 3),
                "gcd": round(float(obs[8]), 3),
                "dn": [int(v * 1000) for v in feats[0].tolist()],
                "ch": [round(float(v), 3) for v in extract_features(obs).tolist()],
                "mobs": mobs,
                "inter": [round(float(obs[ib]), 2), round(float(obs[ib + 1]) * 40, 1), round(float(obs[ib + 4]), 0)],
                "qtarget": ([round(target["x"], 1), round(target["z"], 1)] if target else None),
                "qkind": g.get("target_kind"),
                "qstate": g.get("quest_state"),
                "qdist": g.get("dist"),
                **({"dnprobe": {"delta": round(probe_frame["dndelta"], 4),
                                "scale": probe_frame["dnscale"],
                                "drive_l1": round(probe_frame["drive_l1"], 3)}}
                   if probe_frame else {}),
                "goal": ({"quest": goal.quest, "mode": goal.mode, "go": goal.go,
                          "source": goal.source} if goal is not None else None),
                **{k: info.get(k) for k in ("level", "xp", "kills", "deaths", "quests_done")},
            })

        obs, r, term, trunc, info = env.step(action)
        ep_reward += float(r)
        if term or trunc:
            print(f"эпизод закончился на шаге {step + 1} (terminated={term}, truncated={trunc})")
            break

    if cortex is not None:
        cortex.stop()
        print(f"[llm] статистика кортекса: {cortex.stats.summary()}")

    dt = time.time() - t0
    print(f"записано {len(frames)} кадров за {dt:.1f} с ({len(frames) / max(dt, 1e-9):.0f} кадр/с), "
          f"последний info: {json.dumps({k: info.get(k) for k in ('level','xp','kills','deaths','quests_done')})}")
    payload = {
        "meta": {
            "policy": args.policy,
            "checkpoint": Path(args.checkpoint).name if ckpt else None,
            "seed": args.seed, "torch_seed": args.torch_seed,
            "feature_encoder": FEATURE_VERSION,
            "obs_size": int(env.observation_space.shape[0]),
            "n_actions": int(env.action_space.n),
            "actions": list(env.action_names),
            "world": {"minX": minx, "maxX": maxx, "minZ": minz, "maxZ": maxz},
            "feature_names": list(getattr(sys.modules["fly_brain"], f"FEATURE_NAMES_{FEATURE_VERSION.upper()}", [])),
            "selector": layout.describe(),
            "quests_seen": sorted(quests_seen),
            "aux": ("cortex" if cortex is not None else ("oracle" if aux_on else "none")),
            "llm": ({"mode": args.llm, "period_s": args.llm_period,
                     "timeout_s": args.llm_timeout, "backend": cortex.backend.name,
                     "stats": cortex.stats.summary()} if cortex is not None else None),
            "brain": brain.describe(),
            "llm_couple": (None if link is None else {
                "mode": args.llm_couple,
                "disconnected": link.disconnected,
                "calibration": (link.projector.calibration_report
                                if link.projector.calibrated else None),
                "report": link.report(),
            }),
        },
        "frames": frames,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    print(f"файл: {args.out} ({args.out.stat().st_size / 1024:.0f} КБ), {len(frames)} кадров")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
