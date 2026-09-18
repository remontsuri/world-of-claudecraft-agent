# Инструменты fly-линии (в архиве)

Вынесено из `hermes/TOOLS.md` 2026-09-18 вместе с архивацией линии.
Пути ниже даны **до** переноса; после него добавь префикс `archive/fly-line/`
(например `bash archive/fly-line/fly-woc/tools/run_checks.sh`).
Состояние линии, незакрытые дефекты и как её воскресить — `archive/fly-line/README.md`.

## Fly-линия (муха + её ветка `backup`)

| Когда | Команда | Успех |
|---|---|---|
| после любой правки линии | `bash fly-woc/tools/run_checks.sh` | `ВСЁ ЗЕЛЁНОЕ` (6 блоков) |
| правки устройства/схемы/памяти | `python3 fly-woc/tools/test_device.py` | `итог: устройство разведено корректно`, 25 проверок |
| контроли топологии | `python3 fly-woc/tools/test_control_graph.py --full` | `итог: контроли корректны` |
| собрать контрольные графы | `python3 fly-woc/tools/make_control_graph.py --mode degree|er --seed N` | рядом со схемой появился файл с блоком `control` (sha источника, seed, счётчики) |
| таблица оракула под сборку | `bash fly-woc/tools/make_quest_oracle.sh <тег игры>` | файл нужной версии; чужая таблица обязана падать с `ValueError` |
| целостность схемы и I/O | `python3 fly-woc/check_io.py` | схема реагирует на вход (не молчит) |
| на машине с GPU | `python3 fly-woc/tools/gpu_check.py --device cuda --bench` | выбрано `cuda`, медиана шага, код возврата 0 |
| какой бэкенд быстрее НА ЭТОЙ карте | `python3 fly-woc/tools/gpu_check.py --device cuda --bench-backends --steps 30 --batch 8` | таблица «медиана/мин/расхождение с scipy» + «быстрее всех: …»; расхождение ≤ 1e-5 |
| параллельный шаг по средам | `python3 fly-woc/tools/test_parallel_envs.py` | «ускорение 7–8x», rewards/dones/obs совпадают поэлементно; выключить — `WOC_ENV_THREADS=1` |
| быстрый путь оракула не разошёлся | `python3 fly-woc/tools/test_quest_oracle.py --parity` | «сверено 4000 наблюдений, расхождений 0» |
| ступени к M1–M3 | `bash fly-woc/tools/accel_m1_m3.sh` | прошло дальше `probe`; нужны `WOC_PYTHON_PATH` и GPU |
| метрики эпизода | `python3 fly-woc/progress_eval.py --device cpu` | строка метрик M0–M4 по условиям `our/rewired/er/...` |
| перепроверить прошлый результат | `fly-woc/outputs/README.md` → команда перепрогона по сохранённым чек-интам | числа совпадают с записанными (иначе — разбираться, что изменилось: схема, окружение, версия игры) |

Важное про числа: после аудита 2026-09-17 на CPU быстрее всех не scipy, а `sparse`
(переведён на CSR: 7.35 мс против 16.4 на B=8) — авто-выбор оставлен прежним, потому
что на старых настройках получены все запушенные результаты, а быстрый путь включается
явно: `--backend sparse` (или `WOC_BRAIN_BACKEND`). Порядок на карте не угадывается —
его показывает `--bench-backends`. Реальные цифры снимаются на машине с GPU.
