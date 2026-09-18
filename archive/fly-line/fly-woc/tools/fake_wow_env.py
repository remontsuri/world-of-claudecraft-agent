"""fake_wow_env.py — заглушка игрового окружения для тестов БЕЗ игры и node.

Зачем: train.py импортирует wow_env на уровне модуля, поэтому проверять
устройство (мозг + readout + маска + оракул) без чекаута игры было нельзя —
и вся эта связка оставалась непроверенной. Заглушка даёт ровно тот интерфейс,
который использует train.py: observation_space, action_space, action_names,
reset(seed), step(a), close().

Раскладка: obs=587 (v0.40.0: 48 способностей, 214 квестов), 61 действие
(13 базовых + 48 способностей) — как в реальной сборке.
"""
from __future__ import annotations

import os
import time

import numpy as np

# Задержка на вызов, как у настоящего окружения (round-trip по каналу node-процесса).
# Нужна, чтобы можно было проверить и замерить параллельный шаг по средам: без неё
# заглушка отвечает мгновенно, и выигрыш от потоков измерять не на чем.
_LATENCY_S = max(0.0, float(os.environ.get("WOC_FAKE_LATENCY_MS", "0") or 0)) / 1000.0

OBS_SIZE = 587
BASE_ACTIONS = ["noop", "forward", "back", "turn_left", "turn_right", "strafe_left",
                "strafe_right", "jump", "target_nearest", "attack", "interact", "stop",
                "eat_drink"]
ABILITY_SLOTS = 48
ACTION_NAMES = BASE_ACTIONS + [f"ability_{i + 1}" for i in range(ABILITY_SLOTS)]
ABILITY_INDICES = [i for i, n in enumerate(ACTION_NAMES) if n.startswith("ability_")]


class _Space:
    def __init__(self, n=None, shape=None):
        self.n = n
        self.shape = shape

    def sample(self):
        return int(np.random.randint(self.n))


class WoWClassicEnv:
    def __init__(self, player_class="warrior", max_steps=1200, rewards=None):
        self.player_class = player_class
        self.max_steps = max_steps
        self.rewards = rewards
        self.observation_space = _Space(shape=(OBS_SIZE,))
        self.action_space = _Space(n=len(ACTION_NAMES))
        self.action_names = ACTION_NAMES
        self.ability_indices = ABILITY_INDICES
        self._steps = 0
        self._rng = np.random.default_rng(0)

    def reset(self, seed=None):
        if _LATENCY_S:
            time.sleep(_LATENCY_S)
        self._steps = 0
        self._rng = np.random.default_rng(0 if seed is None else seed)
        obs = self._rng.random(OBS_SIZE, dtype=np.float32) * 0.5
        obs[8] = 1.0                                   # GCD тикает -> маска работает
        return obs, {"level": 1, "xp": 0, "kills": 0, "deaths": 0, "quests_done": 0}

    def step(self, action: int):
        if _LATENCY_S:
            time.sleep(_LATENCY_S)
        self._steps += 1
        obs = self._rng.random(OBS_SIZE, dtype=np.float32) * 0.5
        obs[8] = 1.0
        info = {"level": 1, "xp": 0, "kills": 0, "deaths": 0, "quests_done": 0}
        return obs, 0.0, False, self._steps >= self.max_steps, info

    def close(self):
        pass

    def restart(self):
        pass
