# GPU: как переключается устройство и как это проверить

Всё, что считает тензоры (схема, читаут, PPO, чек-ин/чек-аут), выбирает устройство
само. CUDA нигде не захардкожена: нет GPU — работает CPU, но **только** если GPU не
просили явно.

## Как выбирается устройство

Приоритет: `--device` → `WOC_DEVICE` → `cuda` → `mps` → `cpu`.

* `--device cuda` / `WOC_DEVICE=cuda` при отсутствии GPU — **ошибка** (`RuntimeError`),
  а не тихий откат. Тихий откат — корень класса багов «в логах GPU, счёт на CPU».
* Алиасы: `gpu`→`cuda`, `metal`→`mps`, `auto`/пусто → авто.

Единая точка: `fly-woc/device_utils.py` (`resolve_device`, `describe_device`,
`device_info`). Старое дерево `src/fly_brain/` использует свой `engine.get_device()`
с той же семантикой (строгий, понимает `WOC_DEVICE`).

## Как запускать

```bash
python train.py            --device auto --policy fly        # авто: cuda, если есть
python train.py            --device cuda:0                   # строго первая карта
WOC_DEVICE=cuda python live_agent.py                         # без флага, через окружение
python progress_eval.py    --device auto --conditions fly
python check_io.py                                           # печатает describe(), состояние
python tools/gpu_check.py  --bench                           # что выбрано + замер шага
```

В логе первого экрана обучения будет строка вида:

```
[train] device: cuda:0 (NVIDIA ... 8.0 ГБ) | доступно: cuda, cpu | torch 2.x+cu121
FlyBrain(backend=edge, device=cuda:0, dtype=float32, n=8835, n_dn=82, edges=1874865)
```

Если там `backend=scipy` при `device=cuda` — это ошибка конфигурации: scipy-бэкенд
это CPU-эталон. Бэкенд схемы: `WOC_BRAIN_BACKEND=auto|edge|sparse|scipy`
(auto: cpu → scipy, иначе edge).

## Как убедиться, что это правда GPU

1. `python tools/gpu_check.py --bench` — печатает выбранное устройство, имя карты,
   объём памяти и медиану шага схемы (с `torch.cuda.synchronize()`, иначе замер врёт).
2. `nvidia-smi` во время обучения: python должен держать память.
3. В логе `device: cuda` + `backend=edge`.
4. Код возврата `gpu_check.py`: 1, если запрошенное устройство недоступно.

Ориентир по скорости: шаг среды (frameSkip 5) ~200 мс, значит шаг схемы должен быть
заметно меньше. На CPU `edge` ~843 мс/шаг (не годится, поэтому auto берёт scipy),
на GPU ожидаем единицы мс — но реальные цифры снимаются только на машине с картой.

## Что нашлось по пути (исправлено)

| Что | Как проявлялось |
|---|---|
| `train.py --help` падал | `%` в тексте помощи argparse принимал за формат: `%o format: an integer is required`. Ломался и usage при ошибке в аргументах |
| Таблица оракула проверялась на первом шаге | несовпадение (224-я таблица при obs=587) всплывало после загрузки окружений; теперь отказ сразу при сборке Runner и при старте `progress_eval` |
| `float(pg)` по тензору с градиентом | держал граф живым на каждом апдейте (утечка, на GPU — риск OOM); добавлен `.detach()` |
| `connectome.build_sparse_weights(device="cpu")` по умолчанию | вызов без device клал 1.87M весов на CPU при модели на GPU; теперь `None` → `get_device()` |
| `da_stdp.DopamineModulatedSTDP(device='cpu')` по умолчанию | то же для STDP-весов |
| `flybrain_8k_gpu.py` / `flybrain_full.py` | своя формула выбора устройства (`device or cuda if available`) → переведены на `device_utils` |

## Проверки

```bash
bash tools/run_checks.sh          # всё, что обязано быть зелёным: 6 блоков
python tools/test_device.py       # приёмка устройства: 24 проверки
```

`test_device.py` гоняется без игры и без GPU (заглушка окружения в `tools/`), проверяет:
строгость резолвера, численную эквивалентность бэкендов, отсутствие скрытого
CPU-состояния, детерминизм, связку Runner (мозг + читаут + маска + оракул) и `--device`.

## Что осталось проверить на машине с GPU

1. `python tools/gpu_check.py --device cuda --bench` — числа и отсутствие провала.
2. Короткий прогон: `python train.py --device cuda --updates 5 --steps 32 --envs 2 --no-bench`.
3. Сверить, что `progress_eval.py --device cuda` даёт те же метрики, что CPU-прогон
   на том же чек-инте (расхождение > 1e-4 — сигнал о разъехавшемся состоянии схемы).
