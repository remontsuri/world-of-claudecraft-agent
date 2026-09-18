# reference/ — доказательства воспроизведения

Всё содержимое получено **в этой же песочнице** из коммита `7200c93` + скачанных заново
данных MaleCNS v1.0. Это наши собственные rollout'ы и логи; чужие результаты здесь не приводятся.

| Файл | Что это |
|---|---|
| `benchmark_v2_repro.json` | повторный `train.py --eval-only --tag v2` (traced-схема). fly-sampled/silenced/untrained совпали с закоммиченным `benchmark_v2.json` 5/5 сидов; `random` расходится — см. VERIFICATION.md §4 |
| `benchmark_fullgraph.json` | те же чекпойнты v2 на схеме из **полной** таблицы связей (`data/circuit-full/`) |
| `eval_v2_repro.log` | лог повторного прогона (traced) |
| `fullgraph_eval.log` | лог прогона на полной таблице (fly-условия) |
| `fullgraph_eval_extended.log` | повторный прогон на полной таблице: fly / fly-sampled / fly-silenced по 5 сидов — все числа совпали с traced-схемой. Остановлен до `fly-untrained`: `mlp`, `openloop`, `random` схему не читают (`train.py:241`), их прогон на полном графе ничего не проверяет |
| `compare_circuits.txt` | поэлементное сравнение traced-схемы и полной (по bodyId) |
| `build_circuit_fullscale.patch` | стриминговая запись `circuit.json` для `fly-woc/build_circuit.py` (для полной таблицы, иначе не влезает в RAM) |
| `SHA256SUMS.txt` | хеши обеих схем и закоммиченного `circuit.json` |
| `longhorizon_eval.log` | полный эпизод сервера (8000 шагов): fly-sampled — 39.47/38.76/39.32 reward, но **уровень 1, 60 xp, 0 киллов, 1 квест**; greedy fly — 8.00 и пусто. Это замер «играет ли муха» |
| `env_crash_test_log.json` | краш-тест `env_robust.py`: 2 окружения, SIGKILL одного node посреди прогона — 10/10 апдейтов, exit 0, `env_crashes` = `0,0,0,0,0,1,1,1,1,1` |
| `progress_eval_smoke.json` | вывод нового `progress_eval.py`: прогресс-метрики (уровень/xp/путь/квесты) и вердикт приёмки M1–M4 |

## Воспроизведение с нуля

```bash
# 1) данные (~1.2 ГБ, публичный бакет, токен не нужен, ~10-60 с)
python3 tools/fetch_malecns.py --out /data/malecns --set circuit --set full --link-project-names

# 2) схемы
cd fly-woc
python3 build_circuit.py /data/malecns /data/circuit-traced    # sha 3514c098…, байт-в-байт как data/circuit.json
mkdir -p /data/full/malecns && ln /data/malecns/{body-annotations-male-cns-v1.0-minconf-0.5,body-neurotransmitters-male-cns-v1.0,connectome-weights-male-cns-v1.0-minconf-0.5}.feather /data/full/malecns/
python3 build_circuit.py /data/full  /data/circuit-full        # sha 3d90919e…, ~58 с, пик RAM 685 МБ

# 3) I/O sanity + оценка
WOC_PYTHON_PATH="D:/woc-game/python" python3 check_io.py
WOC_PYTHON_PATH="D:/woc-game/python" python3 train.py --eval-only --tag v2 --eval-episodes 5 \
  --rewards '{"xp": 0.02, "kill": 1.0, "timePenalty": 0.001, "questProgress": 1.0, "questDone": 10}'
```

Ожидаемые числа (traced-схема и полная дают одинаковый результат):
`fly-sampled` → 23.688 / 23.568 / 23.434 / 2.048 / 23.592 (mean **+19.266**),
`fly-silenced` и `fly-untrained` → 1.200 ×5.

## Известные ограничения

- `random`-baseline невоспроизводим: `WoWClassicEnv.reset()` не сидит RNG `action_space` (VERIFICATION.md §4).
- Верифицирован инференс обученных весов, не обучение с нуля; один training seed.
- «Полная таблица» = полный набор связей min-conf 0.5, а не полный коннектом: клеток в DN-центрической схеме столько же (8 836 из 211 577).
