# WoC Agent — Standing Rules

Этот файл загружается автоматически при работе в директории D:\world-of-claudecraft.
Следуй этим правилам ВСЕГДА.

---

## 📌 Архитектура проекта

### Основные компоненты

| Путь | Назначение |
|------|------------|
| `fly-woc/` | Мозг мухи: MaleCNS circuit, PPO readout, benchmarks |
| `python/` | Python-обёртки для WoC среды (wow_env.py, gym_env.py) |
| `src/fly_brain/` | Исходный код RL агента (старый) |
| `woc/` | Headless env_server.ts + Python Gym bindings |
| `malecns/` | Данные MaleCNS v1.0 (annotations, neurotransmitters) |
| `repos/` | Клонированные референсные проекты (doomfly, fly-craftax, flyjump, flyt3) |
| `fly-reference/` | Аналитические документы (FLY_BRAIN_REFERENCE.md, лицензии) |

### Внешние источники

| Путь | Назначение |
|------|------------|
| `D:\woc` | Официальный источник игры (source of truth) |
| `D:\woc-game` | Клонированный levy-street/world-of-claudecraft |
| `D:\world-of-claudecraft-agent` | Устаревшая папка агента (не использовать) |

---

## Git Rules (CRITICAL)

- **Ветка**: ТОЛЬКО backup
- **Remote**: ТОЛЬКО backup (remontsuri/world-of-claudecraft-agent)
- **Запрещено**: release/*, main, master, levy-street для push
- **Большие файлы**: Git LFS для >100MB, иначе GitHub Releases

---

## Fly-WoC — Мозг Мухи

### Архитектура

```
WoC observation (607 float32)
    ↓
13 engineered features (Fly Dino mapping)
    ↓
FROZEN MaleCNS circuit (8 835 cells / 1 874 865 edges)
    ↓ leaky-tanh rate, 3 iterations, scipy.sparse CSR
82 DN (descending neurons) activities
    ↓
Trainable readout MLP (82→64→61 actor, 82→64→1 critic) — PPO
    ↓
Discrete(61) actions in WoC
```

### Ключевые файлы

| Файл | Назначение |
|------|------------|
| `fly-woc/data/circuit.json` | Граф MaleCNS (26 MB) |
| `fly-woc/data/manifest.json` | SHA-256 источников |
| `fly-woc/train.py` | PPO обучение + benchmark |
| `fly-woc/fly_brain.py` | Frozen MaleCNS engine + feature extraction |
| `fly-woc/agent.py` | FlyBrainReadout + MLPControl |
| `fly-woc/build_circuit.py` | Сборка circuit из MaleCNS |
| `fly-woc/check_io.py` | I/O sanity check (obs→DN→readout) |
| `fly-woc/outputs/params_fly_v2.pt` | Обученные веса (+19.27 reward) |
| `fly-woc/outputs/benchmark_v2.json` | Бенчмарк с 6 контролями |

### Запуск

```bash
cd D:/world-of-claudecraft/fly-woc
WOC_PYTHON_PATH="D:/woc-game/python" python check_io.py
WOC_PYTHON_PATH="D:/woc-game/python" python train.py --policy fly --updates 600 --steps 128 --envs 1 --seed 20260915 --rewards '{"xp": 0.02, "kill": 1.0, "timePenalty": 0.001, "questProgress": 1.0, "questDone": 10}'
```

---

## WoC — Headless Environment

### Протокол

- `env_server.ts` — NDJSON over stdin/stdout
- Команды: `info`, `reset`, `step`, `gathering`, `gathering_goal`, `close`
- Награды: `xp`, `kill`, `death`, `questDone`, `questProgress`, `levelUp`, `timePenalty`

### Сборка

```bash
cd D:/woc-game
npm install esbuild && npx esbuild headless/env_server.ts --bundle --platform=node --format=cjs --outfile=dist-env/env_server.cjs
```

### Python wrapper

```python
from wow_env import WoWClassicEnv
env = WoWClassicEnv(player_class="warrior", max_steps=1200)
obs, info = env.reset(seed=42)
obs, reward, terminated, truncated, info = env.step(0)
```

---

## MaleCNS — Данные коннектома

### Источник

- FlyEM/HHMI Janelia (CC BY 4.0)
- MaleCNS v1.0, min confidence 0.5, traced-only edges

### Структура отбора

| Критерий | Результат |
|----------|-----------|
| Descending neurons | 1 314 cells |
| P1 (партнёры DN) | 4 000 cells |
| P2 (партнёры P1) | 4 097 cells |
| Внутренние рёбра | 1 874 865 edges |
| Synaptic contacts | 15 800 512 |

### SHA-256 источников

```
annotations.feather: 2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2
neurotransmitters.feather: 95c9289220663abeb3409f3ad9e5a7f8a53f8093f5139d15502cd08da8879621
edges-traced.feather: 9b3beab17bad5f618be3f2c02d3139a8d07b822565919c013f1e5506d93e604b
```

---

## Референсные проекты (repos/)

| Проект | Лицензия | Граф | Результат |
|--------|----------|------|-----------|
| flyjump (Fly Dino) | Cobanov Template Attribution 1.0 | 80 cells | 99/100 held-out |
| fly-craftax | MIT | ~146k non-VNC | reward↑, survival↓ |
| flyt3 | **без лицензии** | 166 700 | 62–74% vs random |
| doomfly | MIT | 166 700 | негативный |

### DN-маппинги

| Функция | Клетки | Источник |
|---------|--------|----------|
| forward | DNp09 | fly-craftax |
| backward | MDN | fly-craftax |
| turn L/R | DNa01+DNa02 | fly-craftax |
| turn | DNp20 | doomfly |
| move + fire | DNpe017 | doomfly |
| escape | DNp01/GF | наш проект |

---

## Key Files (актуальные)

### Fly-WoC
- `fly-woc/README.md` — протокол, архитектура, результаты
- `fly-woc/train.py` — PPO training + benchmark
- `fly-woc/fly_brain.py` — Frozen MaleCNS engine
- `fly-woc/agent.py` — Trainable readouts

### WoC
- `woc/env_server.ts` — Headless RL server
- `woc/python/wow_env.py` — Gymnasium wrapper

### Данные
- `malecns/annotations.feather` — 14.5 MB
- `malecns/neurotransmitters.feather` — 43.3 MB

### Аналитика
- `fly-reference/FLY_BRAIN_REFERENCE.md` — кросс-проектный анализ
- `fly-reference/THIRD_PARTY_NOTICES.template.md` — шаблон notices

---

## What to Never Do

1. ❌ Kill hermes-agent/hermes-gateway processes
2. ❌ Reload game via CDP
3. ❌ Push to non-backup remotes
4. ❌ Work in D:\world-of-claudecraft-agent
5. ❌ Modify game source code in D:\woc
6. ❌ Commit 1GB connectome-weights.feather (использовать Releases)
7. ❌ Copy code from flyt3 (no license)

---

## User Preferences

- Language: Russian
- Tone: Direct, no filler, no "great question!"
- Verification: Real game behavior > tests
- Workflow: Phase-1 root-cause → TDD → live verification
- Reporting: Tables LAYER|EXPECTED|ACTUAL|STATUS
