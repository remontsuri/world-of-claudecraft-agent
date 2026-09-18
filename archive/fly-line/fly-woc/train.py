"""Train the fly-brain readout on world-of-claudecraft with PPO, then evaluate
it against the full control battery and export every rollout as evidence.

Architecture (identical pattern in Fly Dino v2, fly-craftax, FLYT3):
    obs -> engineered features -> FROZEN MaleCNS circuit -> DN activities
        -> trainable readout (actor/critic) -> Discrete(61) action
The circuit, drive mapping and dynamics are never trained.

Controls (reference: FLY_BRAIN_REFERENCE.md section 6):
  fly            trained readout on circuit activity
  fly-silenced   same trained readout, circuit activity zeroed
  fly-untrained  same architecture, untrained init (same seed)
  mlp            same PPO budget on raw obs, no brain (negative control)
  random         uniform actions
  openloop       forward/attack alternation (fly-craftax 'alternate' control)

Usage:
  python3 train.py --policy fly --updates 400 --seed 20260914
  python3 train.py --policy mlp --updates 400 --seed 20260914
  python3 train.py --eval-only                # benchmark from saved params
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from device_utils import describe_device, device_info, resolve_device

# Path to the world-of-claudecraft checkout containing python/wow_env.py.
# Override with WOC_PYTHON_PATH (e.g. D:/world-of-claudecraft/python on Windows).
WOC_PYTHON = os.environ.get("WOC_PYTHON_PATH", "D:/woc-game/python")
sys.path.insert(0, WOC_PYTHON)
from wow_env import WoWClassicEnv  # noqa: E402

# Robust env: captures the node server's stderr (the base class sends it to
# DEVNULL, which is why a dead server only showed up as OSError Errno 22 on
# Windows) and restarts a crashed server instead of killing the whole run.
try:
    from env_robust import RobustWoWEnv as _EnvClass, EnvServerDied  # noqa: E402
except Exception:                      # no game checkout / base env import failed
    _EnvClass, EnvServerDied = WoWClassicEnv, RuntimeError

from fly_brain import FlyBrain, extract_features  # noqa: E402
from agent import FlyBrainReadout, MLPControl  # noqa: E402

OUT = Path(__file__).parent / "outputs"


# ------------------------------------------------------------------ env batch
class EnvBatch:
    def __init__(self, n: int, max_steps: int, player_class: str, rewards: dict | None = None,
                 args=None):
        self.envs = [_EnvClass(player_class=player_class, max_steps=max_steps, rewards=rewards)
                     for _ in range(n)]
        self.env_crashes = 0
        self.n = n
        self.obs = np.zeros((n, self.envs[0].observation_space.shape[0]), np.float32)
        self.ep_return = np.zeros(n); self.ep_len = np.zeros(n, np.int64)
        self.last_infos = [{} for _ in range(n)]
        self.max_crashes = int(os.environ.get("WOC_MAX_ENV_CRASHES", "100"))
        self.finished: list[dict] = []
        # Среда на шаг = один round-trip по каналу node-процесса. Последовательный
        # цикл по 8 средам — это 8 таких round-trip'ов подряд, и GPU всё это время
        # ждёт (на CPU-прогонах доля ещё выше). У каждой среды свой процесс и свой
        # stdin/stdout, поэтому среды можно вести потоками: одну среду в один момент
        # трогает ровно один поток, а учёт (obs/rewards/dones/ep_return) остаётся в
        # главном. WOC_ENV_THREADS=1 возвращает прежнее поведение (по умолчанию —
        # по потоку на среду, не больше 16).
        want = int(os.environ.get("WOC_ENV_THREADS") or n)
        self.threads = max(1, min(want, max(1, n), 16))
        self._pool = ThreadPoolExecutor(max_workers=self.threads) if self.threads > 1 else None
        if self._pool is not None:
            print(f"[env] {n} сред в {self.threads} потоках (WOC_ENV_THREADS=1 — выключить)", flush=True)
        # Quest-oracle shaping (quest_oracle.py): the obs shows a target only within
        # 1.5*40 = 60 units, but the first quest giver stands ~750 units away, so the
        # quest chain is unreachable by reward alone. Give the policy a gradient:
        # reward for closing the distance to the next objective of the next quest.
        self.oracle = None
        self.oracle_w = float(getattr(args, "oracle_shaping", 0.0) or 0.0)
        self.prev_dist: list[float | None] = [None] * n
        self.prev_quest: list[str | None] = [None] * n
        self.shaped_total = 0.0
        if self.oracle_w:
            from quest_oracle import load_table, guidance_from_obs
            self.oracle, self._guidance = load_table(), guidance_from_obs
            print(f"[oracle] shaping on, weight {self.oracle_w} "
                  f"({len(self.oracle['quests'])} quests)", flush=True)

    def reset(self, seeds: list[int]):
        results = self._map(self._reset_one, list(enumerate(seeds)))
        for i, (obs, crash) in enumerate(results):
            if crash:
                self.env_crashes += 1
                print(f"[train] env {i} server died during reset; restarted "
                      f"(total crashes {self.env_crashes})", flush=True)
            self.obs[i] = obs
        self.ep_return[:] = 0; self.ep_len[:] = 0; self.finished.clear()

    def _map(self, fn, items):
        """Прогнать fn по средам: в пуле — потоками, иначе — как раньше, подряд.

        Порядок результатов сохраняется (map), поэтому учёт в главном потоке не
        зависит от того, какая среда ответила первой: прогоны воспроизводимы.
        """
        if self._pool is None:
            return [fn(item) for item in items]
        return list(self._pool.map(fn, items))

    def _reset_one(self, item):
        i, seed = item
        try:
            obs, _ = self._reset_env(self.envs[i], seed=seed)
            return obs, False
        except EnvServerDied:
            return self.obs[i], True

    def _reset_env(self, env, seed: int | None = None):
        """reset() that survives a dead server (the wrapper retries internally)."""
        try:
            return env.reset(seed=seed) if seed is not None else env.reset()
        except EnvServerDied as exc:
            self.env_crashes += 1
            first = str(exc).splitlines()[0]
            print(f"[train] env server died during reset ({first}); restarting "
                  f"(total crashes {self.env_crashes})", flush=True)
            env.restart()
            return env.reset(seed=seed) if seed is not None else env.reset()

    def _step_one(self, item):
        """Шаг одной среды. Выполняется в потоке-воркере и НЕ трогает общий учёт.

        Возвращает (crash, r, term, trunc, info, shaped, obs_next):
          crash   — сервер среды умер, шаг потерян (transition не выдумываем);
          shaped  — добавка за сокращение дистанции (0.0, если шейпинг выключен);
          obs_next— наблюдение для следующего шага (при конце эпизода — уже
                    свежий reset, как и раньше: авто-reset делает сам воркер,
                    иначе он бы сериализовал потоки).
        """
        i, action = item
        env = self.envs[i]
        try:
            o, r, term, trunc, info = env.step(int(action))
        except EnvServerDied as exc:
            # Смерть сервера среды (node OOM, необработанный throw): перезапускаем,
            # начинаем эпизод заново. Сам учёт и печать — в главном потоке.
            first = str(exc).splitlines()[0]
            try:
                env.restart()
                o, _ = env.reset()
            except Exception as exc2:                    # noqa: BLE001
                return (None, i, f"{first} (и повторный старт не удался: {exc2})", 0.0, False, False, {}, 0.0, None)
            return (True, i, first, 0.0, False, False, {}, 0.0, o)
        shaped = 0.0
        if self.oracle is not None:
            g = self._guidance(o, table=self.oracle)
            qid, dist = g.get("quest"), g.get("dist")
            if qid is not None and dist is not None and qid == self.prev_quest[i] \
                    and self.prev_dist[i] is not None:
                shaped = self.oracle_w * float(np.clip((self.prev_dist[i] - dist) / 40.0, -1.0, 1.0))
            if qid is not None:
                self.prev_quest[i], self.prev_dist[i] = qid, dist
        obs_next = o
        if term or trunc:
            obs_next, _ = env.reset()                   # авто-reset; свежий obs
        return (False, i, None, r, term, trunc, info, shaped, obs_next)

    def step(self, actions: np.ndarray):
        dones = np.zeros(self.n, bool)
        rewards = np.zeros(self.n, np.float32)
        results = self._map(self._step_one, list(zip(range(self.n), np.asarray(actions).tolist())))
        for crash, i, detail, r, term, trunc, info, shaped, obs_next in results:
            if crash is None:
                raise EnvServerDied(f"env {i}: {detail}")
            if crash:
                self.env_crashes += 1
                print(f"[train] env {i} server died ({detail}); restarting "
                      f"(total crashes {self.env_crashes})", flush=True)
                if self.env_crashes > self.max_crashes:
                    raise EnvServerDied(f"среды падали больше {self.max_crashes} раз: {detail}")
                self.ep_return[i] = 0; self.ep_len[i] = 0
                self.prev_dist[i] = self.prev_quest[i] = None
                if obs_next is not None:
                    self.obs[i] = obs_next
                continue
            if shaped:
                r = float(r) + shaped
                self.shaped_total += shaped
            self.obs[i] = obs_next
            rewards[i] = r
            self.ep_return[i] += r; self.ep_len[i] += 1
            self.last_infos[i] = info
            if term or trunc:
                dones[i] = True
                self.finished.append({
                    "steps": int(self.ep_len[i]), "reward": round(float(self.ep_return[i]), 4),
                    **{k: info.get(k) for k in ("level", "xp", "kills", "deaths", "quests_done", "copper")},
                })
                self.ep_return[i] = 0; self.ep_len[i] = 0
                self.prev_dist[i] = self.prev_quest[i] = None
        return dones, rewards

    def close(self):
        for env in self.envs:
            env.close()
        if self._pool is not None:
            self._pool.shutdown(wait=False)


# ------------------------------------------------------------------ policy runner
class Runner:
    """One brain instance + one policy net; produces actions and PPO tensors."""

    def __init__(self, args, n_envs: int, obs_dim: int, n_actions: int, device=None):
        self.args = args
        # Устройство одно на весь раннер: мозг считает на нём же, где живёт readout.
        # Раньше FlyBrain(device=...) игнорировал параметр и работал на CPU, а сеть
        # уезжала на GPU — отсюда переносы тензоров в каждом шаге.
        self.device = resolve_device(device)
        self.brain = (FlyBrain(device=self.device, backend=getattr(args, "backend", None))
                      if args.policy == "fly" else None)
        if self.brain is not None:
            print(f"[brain] {self.brain.describe()}"
                  + ("" if getattr(args, "backend", None) else "  (авто; WOC_BRAIN_BACKEND или "
                     "--backend меняют, замер — gpu_check.py --bench-backends)"), flush=True)
        self.oracle_table = None
        self._oracle_vector = None
        if getattr(args, "oracle_obs", False) and args.policy == "fly":
            # Функция — в атрибуте, а не через `global`: прежний вариант объявлял
            # глобальную переменную, которую никто не присваивал, и работал только
            # потому, что импорт внутри __init__ попадал в глобальные имена модуля.
            from quest_oracle import load_table, oracle_vector
            self._oracle_vector = oracle_vector
            self.oracle_table = load_table()
            # Сверка таблицы со сборкой СРАЗУ: иначе несовпадение (224-я таблица на
            # obs=587) всплывало бы только на первом шаге обучения, уже после загрузки
            # окружений и прогрева.
            self._oracle_vector(np.zeros(obs_dim, dtype=np.float32), table=self.oracle_table)
            print(f"[oracle] side channel into the readout: +5 inputs "
                  f"({len(self.oracle_table['quests'])} quests)", flush=True)
        if args.policy == "fly":
            torch.manual_seed(args.seed)
            extra = 5 if self.oracle_table is not None else 0
            self.net = FlyBrainReadout(self.brain.n_dn + extra, n_actions).to(self.device)
        else:
            torch.manual_seed(args.seed)
            self.net = MLPControl(obs_dim, n_actions).to(self.device)
        self.opt = torch.optim.Adam(self.net.parameters(), lr=args.lr)
        self.n_actions = n_actions
        # Ability actions are gated by the game's GCD: casting again while it
        # ticks mostly queues/voids. Measured on the committed v2 checkpoint:
        # 71.6% of steps were ability casts spread over all 48 slots, i.e. the
        # policy spent most of an episode on a 1-per-GCD resource.
        self.mask_abilities = getattr(args, "mask_abilities", False)
        self.ability_idx = getattr(args, "ability_idx", None)

    def oracle_extra(self, obs: np.ndarray) -> torch.Tensor | None:
        """Боковой канал: 5 чисел «где следующая цель квеста» (quest_oracle.py).

        Зачем именно так: obs показывает цель только в 60 юнитах, а первый NPC
        стоит в ~750 — без этого входа политика учится навигации вслепую
        (шейпинг награды даёт градиент, но не признак направления). Схема при
        этом не переобучается: вектор подаётся прямо в readout, а не в цепь.
        """
        if self.oracle_table is None:
            return None
        rows = [self._oracle_vector(o, table=self.oracle_table) for o in obs]
        return torch.tensor(np.stack(rows), dtype=torch.float32).to(self.device)

    def feats(self, obs: np.ndarray, silenced: bool = False) -> torch.Tensor:
        if self.brain is not None:
            f = np.stack([extract_features(o) for o in obs])
            # Признаки приезжают на устройство мозга один раз на батч; наружу
            # brain.step отдаёт тензор на своём устройстве — переносить нечего.
            base = self.brain.step(torch.as_tensor(f, device=self.device), silenced=silenced)
            extra = self.oracle_extra(obs)
            return base if extra is None else torch.cat([base, extra], dim=1)
        return torch.as_tensor(obs, device=self.device)

    def episode_reset(self, batch: int):
        if self.brain is not None:
            self.brain.reset(batch)

    def reset_done(self, dones: np.ndarray) -> None:
        """Reset MaleCNS state for environments that just auto-reset."""
        if self.brain is not None:
            mask = np.asarray(dones, dtype=bool)
            if mask.any():
                self.brain.zero_rows(mask)

    @torch.no_grad()
    def act(self, feats: torch.Tensor, mask: torch.Tensor | None = None,
            deterministic: bool = False):
        logits, value = self.net(feats)
        if mask is not None:
            logits = logits.masked_fill(~mask, -1e9)
        dist = torch.distributions.Categorical(logits=logits)
        a = logits.argmax(-1) if deterministic else dist.sample()
        return a.cpu().numpy(), dist.log_prob(a), value, dist.entropy()


# ------------------------------------------------------------------ PPO
def ppo_update(net, opt, batch, clip=0.2, ent_coef=0.02, vf_coef=0.5, epochs=4, mb=64):
    """mask: (N, n_actions) True = allowed; must match the mask used at sampling,
    otherwise the importance ratio is computed against a different policy."""
    n = batch["feats"].shape[0]
    adv = batch["adv"]
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    stats = {}
    for _ in range(epochs):
        perm = torch.randperm(n)
        for s in range(0, n, mb):
            ix = perm[s:s + mb]
            logits, value = net(batch["feats"][ix])
            if batch.get("mask") is not None:
                logits = logits.masked_fill(~batch["mask"][ix], -1e9)
            dist = torch.distributions.Categorical(logits=logits)
            logp = dist.log_prob(batch["action"][ix])
            ratio = torch.exp(logp - batch["logp"][ix])
            pg = -torch.min(ratio * adv[ix], ratio.clamp(1 - clip, 1 + clip) * adv[ix]).mean()
            v_clip = batch["value"][ix] + (value - batch["value"][ix]).clamp(-clip, clip)
            vf = 0.5 * torch.max((value - batch["ret"][ix]) ** 2, (v_clip - batch["ret"][ix]) ** 2).mean()
            ent = dist.entropy().mean()
            loss = pg + vf_coef * vf - ent_coef * ent
            opt.zero_grad(); loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 0.5)
            opt.step()
            stats = {"pg": float(pg.detach()), "vf": float(vf.detach()), "ent": float(ent.detach())}
    return stats


def compute_gae(rewards, values, dones, last_value, gamma=0.99, lam=0.95):
    """rewards/values/dones: (T, B); last_value: (B,)."""
    adv = torch.zeros_like(rewards)
    last = torch.zeros_like(last_value)
    T = len(rewards)
    for t in reversed(range(T)):
        nonterm = 1.0 - dones[t].float()
        next_v = last_value if t == T - 1 else values[t + 1]
        delta = rewards[t] + gamma * next_v * nonterm - values[t]
        last = delta + gamma * lam * nonterm * last
        adv[t] = last
    return adv, adv + values


def ability_mask(obs: np.ndarray, ability_idx, n_actions: int, gcd_threshold: float = 1e-3, device: str = "cpu"):
    """True = action allowed. src/sim/obs.ts: obs[8] = gcdRemaining / GCD, so any
    value above the threshold means abilities are on cooldown and a cast would
    only queue."""
    o = np.asarray(obs, dtype=np.float32)
    allowed = np.ones((o.shape[0], n_actions), dtype=bool)
    if ability_idx is None or not len(ability_idx):
        return torch.as_tensor(allowed, device=device)
    ticking = np.nonzero(o[:, 8] > gcd_threshold)[0]
    if len(ticking):
        allowed[np.ix_(ticking, np.asarray(ability_idx))] = False
    return torch.as_tensor(allowed, device=device)


def train(args):
    OUT.mkdir(exist_ok=True)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    rewards = json.loads(args.rewards) if args.rewards else None
    batch = EnvBatch(args.envs, args.max_steps, args.player_class, rewards=rewards, args=args)
    obs_dim = batch.envs[0].observation_space.shape[0]
    n_actions = batch.envs[0].action_space.n
    action_names = batch.envs[0].action_names
    args.ability_idx = [i for i, name in enumerate(action_names) if name.startswith("ability_")]
    # Раскладка obs: выводим из окружения (длина obs + число действий), иначе
    # на сборке с другим числом квестов энкодер прочитает чужие поля.
    from obs_layout import configure as _configure_layout
    _layout = _configure_layout(obs_size=int(batch.obs.shape[1]), n_actions=n_actions)
    print(f"[obs] {_layout.describe()}", flush=True)
    device = resolve_device(getattr(args, "device", None))
    info = device_info()
    print(f"[train] device: {describe_device(device)} | доступно: {info['devices']} | torch {info['torch']}", flush=True)
    runner = Runner(args, args.envs, obs_dim, n_actions, device=device)
    batch.reset([int(rng.integers(1, 900000)) for _ in range(args.envs)])
    runner.episode_reset(args.envs)

    log = []
    t0 = time.time()
    for update in range(1, args.updates + 1):
        buf = {"feats": [], "action": [], "logp": [], "value": [], "reward": [], "done": [],
               "mask": []}
        for _ in range(args.steps):
            feats = runner.feats(batch.obs)
            mask = (ability_mask(batch.obs, runner.ability_idx, n_actions, device=runner.device)
                    if runner.mask_abilities else None)
            actions, logp, value, _ = runner.act(feats, mask=mask)
            buf["mask"].append(mask if mask is not None else torch.ones(len(batch.obs), n_actions, dtype=torch.bool, device=runner.device))
            dones, rewards = batch.step(actions)
            runner.reset_done(dones)
            buf["feats"].append(feats); buf["action"].append(torch.as_tensor(actions, device=runner.device))
            buf["logp"].append(logp); buf["value"].append(value)
            buf["reward"].append(torch.as_tensor(rewards, device=runner.device))
            buf["done"].append(torch.as_tensor(dones, device=runner.device))
        stats = _finish_update(runner, buf, batch)
        ep = list(batch.finished); batch.finished.clear()
        row = {"update": update, "seconds": round(time.time() - t0, 1), **stats,
               "episodes": len(ep), "env_crashes": batch.env_crashes,
               "oracle_shaped": round(batch.shaped_total, 3)}
        if ep:
            row["ep_return"] = round(float(np.mean([e["reward"] for e in ep])), 4)
            row["ep_len"] = round(float(np.mean([e["steps"] for e in ep])), 1)
            row["max_level"] = int(max(e["level"] for e in ep))
            row["total_kills"] = int(sum(e["kills"] for e in ep))
        log.append(row)
        for e in ep:
            print(f"  [ep] update {update:4d} steps {e['steps']:5d} ret {e['reward']:8.3f} "
                  f"lvl {e.get('level')} kills {e.get('kills')} quests {e.get('quests_done')}",
                  flush=True)
        if args.ckpt_every and update % args.ckpt_every == 0:
            tag_now = f"_{args.tag}" if args.tag else ""
            torch.save({"state": runner.net.state_dict(), "seed": args.seed, "updates": update,
                        "policy": args.policy, "n_actions": n_actions,
                        "oracle_obs": getattr(args, "oracle_obs", False)},
                       OUT / f"params_{args.policy}{tag_now}.pt")
            (OUT / f"train_log_{args.policy}{tag_now}.json").write_text(json.dumps(
                {"config": vars(args), "log": log, "env_crashes": batch.env_crashes}, indent=1))
            print(f"  [ckpt] update {update} -> outputs/params_{args.policy}{tag_now}.pt", flush=True)
        if update % 10 == 0 or update == 1:
            print(f"update {update:4d} | {row.get('episodes', 0):3d} eps | "
                  f"ret {row.get('ep_return', float('nan')):8.3f} | len {row.get('ep_len', float('nan')):6.1f} | "
                  f"lvl {row.get('max_level', '-')} | ent {stats['ent']:.3f} | {row['seconds']:.0f}s"
                  + (f" | shaped {row['oracle_shaped']:+.2f}" if batch.oracle_w else ""), flush=True)

    tag = f"_{args.tag}" if args.tag else ""
    params_path = OUT / f"params_{args.policy}{tag}.pt"
    torch.save({"state": runner.net.state_dict(), "seed": args.seed, "updates": args.updates,
                "policy": args.policy, "n_actions": n_actions,
                "oracle_obs": getattr(args, "oracle_obs", False)}, params_path)
    (OUT / f"train_log_{args.policy}{tag}.json").write_text(json.dumps(
        {"config": vars(args), "log": log, "env_crashes": batch.env_crashes}, indent=1))
    print("saved", params_path)
    batch.close()


def _finish_update(runner, buf, batch):
    """Assemble rollout tensors (per-env rewards were captured in step) and update."""
    feats = torch.stack(buf["feats"]); action = torch.stack(buf["action"])
    logp = torch.stack(buf["logp"]); value = torch.stack(buf["value"])
    reward = torch.stack(buf["reward"]); done = torch.stack(buf["done"])
    # V(s_T) needs one extra brain step. Restore the pre-value state so the
    # next rollout does not process the same observation twice.
    # Снимок состояния схемы — через state_copy()/restore_state(): у scipy это
    # numpy-массив (.copy()), у torch-бэкендов (edge/sparse, то есть на GPU) —
    # тензор, у которого метода .copy() нет вообще. Прежняя строка
    # `runner.brain.h.copy()` роняла обучение на первом же апдейте с
    # AttributeError, как только мозг считался не numpy-путём.
    brain_h_backup = runner.brain.state_copy() if runner.brain is not None else None
    with torch.no_grad():
        last_value = runner.net(runner.feats(batch.obs))[1]
    if brain_h_backup is not None:
        runner.brain.restore_state(brain_h_backup)
    adv, ret = compute_gae(reward, value, done, last_value,
                           gamma=runner.args.gamma, lam=runner.args.lam)
    mask = torch.stack(buf["mask"]).reshape(-1, feats.shape[-1] and buf["mask"][0].shape[-1]) \
        if runner.mask_abilities else None
    stats = ppo_update(runner.net, runner.opt, {
        "feats": feats.reshape(-1, feats.shape[-1]), "action": action.reshape(-1),
        "logp": logp.reshape(-1), "value": value.reshape(-1),
        "adv": adv.reshape(-1), "ret": ret.reshape(-1), "mask": mask})
    return stats


# ------------------------------------------------------------------ evaluation
_ACTION_NAMES: list[str] | None = None


def evaluate(args, policy_kind: str, params: dict | None, n_episodes: int, seed0: int):
    """One env, fixed seeds. policy_kind: fly|fly-silenced|fly-untrained|mlp|random|openloop"""
    global _ACTION_NAMES
    rewards = json.loads(args.rewards) if args.rewards else None
    env = _EnvClass(player_class=args.player_class, max_steps=args.max_steps, rewards=rewards)
    from obs_layout import configure as _configure_layout
    print(f"[obs] {_configure_layout(obs_size=env.observation_space.shape[0], n_actions=env.action_space.n).describe()}", flush=True)
    _ACTION_NAMES = env.action_names
    if getattr(args, "mask_abilities", False):
        args.ability_idx = [i for i, name in enumerate(env.action_names) if name.startswith("ability_")]
    n_actions = env.action_space.n
    obs_dim = env.observation_space.shape[0]
    sampled = policy_kind.endswith("-sampled")
    base = policy_kind[:-len("-sampled")] if sampled else policy_kind
    dev = resolve_device(getattr(args, "device", None))
    brain = (FlyBrain(device=dev, backend=getattr(args, "backend", None))
             if base.startswith("fly") else None)

    # Determine oracle usage: explicit flag > checkpoint shape > default
    oracle_tbl, net_extra = None, False
    use_oracle = getattr(args, "oracle_obs", False)
    if not use_oracle and base.startswith("fly") and params is not None:
        w = params["state"].get("actor.0.weight") if isinstance(params, dict) else None
        if w is not None and brain is not None and w.shape[-1] == brain.n_dn + 5:
            use_oracle = True
    if use_oracle:
        from quest_oracle import load_table, oracle_vector
        oracle_tbl, net_extra = load_table(), True
        oracle_vector(np.zeros(obs_dim, dtype=np.float32), table=oracle_tbl)   # fail-fast
        print("[eval] oracle side channel detected (+5 inputs)", flush=True)
    net = None
    if base.startswith("fly"):
        torch.manual_seed(args.seed)
        extra = 5 if use_oracle else 0
        net = FlyBrainReadout(brain.n_dn + extra, n_actions).to(dev)
        if params is not None and base != "fly-untrained":
            net.load_state_dict(params["state"])
    elif base.startswith("mlp"):
        net = MLPControl(obs_dim, n_actions).to(dev)
        if params is not None:
            net.load_state_dict(params["state"])
    net.eval() if net is not None else None
    episodes = []
    for k in range(n_episodes):
        seed = seed0 + k
        obs, info = env.reset(seed=seed)
        if brain is not None:
            brain.reset(1)
        total = 0.0; steps = 0
        crashes = 0
        trace = []
        prev_events = {"kills": 0, "deaths": 0, "quests_done": 0, "level": 1}
        while True:
            if policy_kind == "random":
                a = int(env.action_space.sample())
            elif policy_kind == "openloop":
                a = 1 if steps % 2 == 0 else 9        # forward / attack
            else:
                with torch.no_grad():
                    if brain is not None:
                        f = brain.step(
                            torch.as_tensor(extract_features(obs)[None], device=dev),
                            silenced=(base == "fly-silenced"))
                        if net_extra:
                            f = torch.cat([f, torch.as_tensor(
                                oracle_vector(obs, table=oracle_tbl)[None], device=dev)], dim=1)
                    else:
                        f = torch.as_tensor(obs[None], device=dev)
                    logits = net(f)[0]
                    if getattr(args, "mask_abilities", False) and getattr(args, "ability_idx", None):
                        m = ability_mask(np.asarray(obs)[None], args.ability_idx, n_actions, device=dev)
                        logits = logits.masked_fill(~m, -1e9)
                    if sampled:
                        a = int(torch.distributions.Categorical(logits=logits).sample())
                    else:
                        a = int(logits.argmax(-1))
            try:
                obs, r, term, trunc, info = env.step(a)
            except EnvServerDied as exc:
                crashes += 1
                if crashes > 5:
                    raise
                first = str(exc).splitlines()[0]
                print(f"  [{policy_kind}] env server died ({first}); restarting + fresh episode",
                      flush=True)
                env.restart()
                obs, _ = env.reset(seed=seed)
                if brain is not None:
                    brain.reset(1)
                total = 0.0; steps = 0
                prev_events = {"kills": 0, "deaths": 0, "quests_done": 0, "level": 1}
                continue
            total += r; steps += 1
            # compact per-step trace: only action changes and game events
            events = {key: info.get(key) for key in ("kills", "deaths", "quests_done", "level")}
            ev_delta = {key: v for key, v in events.items() if v != prev_events.get(key)}
            if ev_delta or (trace and trace[-1][1] != a) or steps == 1:
                trace.append([steps, a, round(total, 3), ev_delta or None])
                prev_events = events
            if term or trunc:
                break
        episodes.append({"seed": seed, "steps": steps, "reward": round(total, 4),
                         "trace_len": len(trace), "trace": trace[-400:],
                         **{key: info.get(key) for key in ("level", "xp", "kills", "deaths", "quests_done")}})
        print(f"  {policy_kind:15s} seed {seed}: steps {steps:5d} reward {total:9.3f} "
              f"lvl {info.get('level')} xp {info.get('xp')} kills {info.get('kills')} "
              f"deaths {info.get('deaths')} quests {info.get('quests_done')}", flush=True)
    env.close()
    summary = {"episodes": len(episodes),
               "mean_reward": round(float(np.mean([e["reward"] for e in episodes])), 4),
               "mean_steps": round(float(np.mean([e["steps"] for e in episodes])), 1),
               "mean_level": round(float(np.mean([e["level"] for e in episodes])), 2),
               "mean_xp": round(float(np.mean([e["xp"] for e in episodes])), 1),
               "total_kills": int(sum(e["kills"] for e in episodes)),
               "total_deaths": int(sum(e["deaths"] for e in episodes)),
               "total_quests": int(sum(e["quests_done"] for e in episodes))}
    return {"condition": policy_kind, "summary": summary, "episodes": episodes}


def benchmark(args):
    OUT.mkdir(exist_ok=True)
    tag = f"_{args.tag}" if args.tag else ""
    fly_path, mlp_path = OUT / f"params_fly{tag}.pt", OUT / f"params_mlp{tag}.pt"
    dev = resolve_device(getattr(args, "device", None))
    fly_params = torch.load(fly_path, weights_only=False, map_location=dev) if fly_path.exists() else None
    mlp_params = torch.load(mlp_path, weights_only=False, map_location=dev) if mlp_path.exists() else None
    results = []
    if args.conditions:
        conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    else:
        conditions = ["fly", "fly-sampled", "fly-silenced", "fly-untrained", "random", "openloop"]
        if mlp_params is not None:
            conditions[2:2] = ["mlp", "mlp-sampled"]
    for cond in conditions:
        base = cond[:-len("-sampled")] if cond.endswith("-sampled") else cond
        params = {"fly": fly_params, "fly-silenced": fly_params, "mlp": mlp_params}.get(base)
        if cond.startswith("fly") and fly_params is None:
            print(f"skip {cond}: no params_fly.pt"); continue
        print(f"[{cond}]")
        results.append(evaluate(args, cond, params, args.eval_episodes, args.eval_seed))
    bench = {"environment": "world-of-claudecraft (levy-street, headless env_server)",
             "env_version": {"obs": 607, "actions": 61},
             "action_names": _ACTION_NAMES,
             "circuit": json.loads((Path(__file__).parent / "data" / "manifest.json").read_text()),
             "eval_config": {"episodes": args.eval_episodes, "seed0": args.eval_seed,
                             "max_steps": args.max_steps, "player_class": args.player_class,
                             "rewards": json.loads(args.rewards) if args.rewards else "server defaults",
                             "tag": args.tag or None},
             "results": results,
             "note": ("Our own exported rollouts are the evidence; upstream project results are not. "
                      "Circuit is a bounded DN-centric subset (circuit subset), frozen; only the "
                      "artificial readout is trained.")}
    out_path = OUT / f"benchmark{tag}.json"
    if args.conditions and out_path.exists():     # merge into the existing benchmark
        prev = json.loads(out_path.read_text())
        by_cond = {r["condition"]: r for r in prev.get("results", [])}
        by_cond.update({r["condition"]: r for r in results})
        bench["results"] = [by_cond[c] for c in
                            (list(prev.get("order", [])) or list(by_cond)) if c in by_cond]
        have = {r["condition"] for r in bench["results"]}
        for r in results:
            if r["condition"] not in have:
                bench["results"].append(r)
        bench["order"] = [r["condition"] for r in bench["results"]]
    out_path.write_text(json.dumps(bench, indent=1))
    print("wrote", out_path)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--device", default=None,
                   help="cuda | cuda:0 | mps | cpu | auto (по умолчанию: WOC_DEVICE, иначе auto)")
    p.add_argument("--backend", default=None,
                   help="бэкенд схемы: scipy | edge | sparse (иначе WOC_BRAIN_BACKEND, иначе auto). "
                        "Что быстрее НА ЭТОЙ карте — замер: tools/gpu_check.py --bench-backends")
    p.add_argument("--policy", choices=["fly", "mlp"], default="fly")
    p.add_argument("--updates", type=int, default=400)
    p.add_argument("--steps", type=int, default=96, help="env steps per env per update")
    p.add_argument("--envs", type=int, default=2)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--seed", type=int, default=20260914)
    p.add_argument("--max-steps", type=int, default=1200, dest="max_steps")
    p.add_argument("--player-class", default="warrior", dest="player_class")
    p.add_argument("--eval-only", action="store_true")
    p.add_argument("--no-bench", action="store_true", dest="no_bench", help="train without the auto benchmark")
    p.add_argument("--eval-episodes", type=int, default=5, dest="eval_episodes")
    p.add_argument("--rewards", default=None, help='JSON dict overriding env rewards')
    p.add_argument("--tag", default="", help="suffix for params/log/benchmark filenames")
    p.add_argument("--conditions", default=None, help="comma-separated subset of conditions to evaluate (merged into existing benchmark)")
    p.add_argument("--eval-seed", type=int, default=900001, dest="eval_seed")
    p.add_argument("--oracle-obs", action="store_true", dest="oracle_obs",
                   help="feed quest-oracle guidance (5 dims) into the readout as a side "
                        "channel; the connectome itself stays frozen");
    p.add_argument("--oracle-shaping", type=float, default=0.0, dest="oracle_shaping",
                   help="reward weight for closing distance to the next quest objective "
                        "(quest_oracle.py); 0 = off")
    p.add_argument("--gamma", type=float, default=0.99,
                   help="discount; raise to ~0.999 when the goal (quest chain) is long")
    p.add_argument("--lam", type=float, default=0.95, help="GAE lambda")
    p.add_argument("--ckpt-every", type=int, default=0, dest="ckpt_every",
                   help="save params/train_log every N updates (survives a reboot); 0 = off")
    p.add_argument("--mask-abilities", action="store_true", dest="mask_abilities",
                   help="block ability actions while the GCD ticks (kills the 71.6%%-of-steps cast spam); "
                        "train and evaluate with the same flag")
    args = p.parse_args()
    if args.eval_only:
        benchmark(args)
    else:
        train(args)
        if not args.no_bench:
            benchmark(args)
