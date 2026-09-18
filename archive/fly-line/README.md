# Архив fly-линии (коннектом мухи)

**Дата архивации:** 2026-09-18 · **HEAD на момент архивации:** `40f3ba6` · **ветка:** `backup`

Решение владельца: активная линия одна — автономный Java-бот (`woof-agent/`) с мостом к игре.
Всё, что относилось к линии «коннектом мухи», переложено сюда **целиком и без удалений**:
180 файлов, `git mv` (в истории — переименования, содержимое побайтово прежнее).

Восстановление любого файла: `git checkout 40f3ba6 -- <старый путь>` или
`git mv archive/fly-line/<...> <...>` обратно.

## Тяжёлые данные сняты с отслеживания (решение владельца, 2026-09-18)

Архив остался в git **кодом, документацией и доказательствами**, но не весами:

| Что | Размер | В git? | Как вернуть |
|---|---|---|---|
| `data/` (три копии коннектома + контроль ER) | 77 МБ | нет | `git checkout 40f3ba6 -- archive/fly-line/data/` или регенерация (§2) |
| `fly-woc/data/circuit.json` (канон, 8835 узлов) | 26 МБ | нет | `git checkout 40f3ba6 -- …/circuit.json`; sha `3514c098…`, собирается `build_circuit.py` из MaleCNS |
| `fly-woc/outputs/*.pt` (чек-инты читаута) | 2.6 МБ | нет | `git checkout 40f3ba6 -- …/outputs/` |
| `fly-woc/viz/scene-full.json` | 0.9 МБ | нет | `git checkout 40f3ba6 -- …/viz/scene-full.json` |
| `fly-woc/data/quest_oracle*.json` (4 таблицы) | 0.3 МБ | **да** | — |
| `fly-woc/outputs/benchmark_*.json` (числа F8 и прежних прогонов) | 3.7 МБ | **да** | — |
| `fly-woc/outputs/train_log_*.json` (конфигурации прогонов) | 1.8 МБ | **да** | — |
| весь код, `tools/`, документы линии | ~0.7 МБ | **да** | — |

Итог: отслеживаемое дерево репозитория 117 МБ → **11 МБ** (231 файл против 258).
Правила — в корневом `.gitignore`, блок «Архив fly-линии». Физически файлы с диска
не удалялись; в свежем клоне их не будет.

---

## 1. Что здесь лежит и откуда оно переехало

| Было | Стало | Что это |
|---|---|---|
| `fly-woc/` | `archive/fly-line/fly-woc/` | вся линия: `train.py`, `progress_eval.py`, `fly_brain.py`, `obs_layout.py`, `quest_oracle.py`, `device_utils.py`, `env_robust.py`, `live_agent.py`, `fly_llm.py`, 28 инструментов в `tools/`, 15 документов, `outputs/` (чек-инты и бенчмарки), `viz/`, `data/` (каноническая схема + 4 таблицы квестов) |
| `src/fly_brain/` | `archive/fly-line/src-fly_brain/` | ранняя линия: LIF-движок, DA-STDP, моторный декодер, `connectome*.py`, `woc_brain_env.py` |
| `data/` | `archive/fly-line/data/` | `circuit-full/circuit.json` (8836 узлов, sha `3d90919e…`), контроли `circuit_er.json` и `circuit_rewired.json` (по 26–27 МБ), `connectome/exported-traced-adjacencies-v1.2/` |
| `reference/` | `archive/fly-line/reference/` | доказательства воспроизведения: `benchmark_v2_repro.json`, `benchmark_fullgraph.json`, логи прогонов, `SHA256SUMS.txt`, патч стриминговой записи схемы |
| `python/` | `archive/fly-line/python/` | `wow_env.py` (gym-обёртка headless-сима игры), `connectome_policy.py`, `engine.py`, `gym_env.py`, `offline_woc_env.py`, `woc_game.py`, `arbitration_layer.py` (в `AGENTS.md` помечен как мёртвый код) |
| `OFFLINE_PLAY.md`, `REMAINING.md`, `VERIFICATION.md` | `archive/fly-line/` | ранбук офлайн-игры, срез «что осталось до полноценной игры», верификация сборки схемы и воспроизведения |
| `knowledge/fly-connectome.md`, `knowledge/fly-experiments.md` | `archive/fly-line/knowledge/` | числа схемы/контролей/LIF/атрибуция MaleCNS и журнал экспериментов |
| `play_fly.py`, `play_fly_live.py`, `train_bc.py`, `train_ppo.py`, `train_ppo_offline.py`, `test_perf.py` | `archive/fly-line/scripts/` | скрипты корня: игра глазами мухи, BC/PPO на старой линии, замер `ConnectomePolicy` |
| `tools/compare_circuits.py`, `tools/fetch_malecns.py`, `tools/push_to_github.sh` | `archive/fly-line/tools/` | сравнение схем, загрузка данных MaleCNS, старый push-скрипт |

**Не архивировано (осталось в корне), потому что к мухе не относится:**

| Файл | Почему остался |
|---|---|
| `recover.py` | клиент моста `:8791` (walk to spirit healer) — инструмент Java-линии, а не мухи |
| `dataset_collector.py` | сбор датасета через `python.woc_game` (мост) для BC — тоже не коннектом |
| `tools/push_backup.sh` | бывший `fly-woc/push_fixes.sh`: общий push-хелпер с fast-forward проверкой, нужен рабочей ветке |
| `knowledge/principles.md`, `pitfalls.md`, `verification.md`, `woc-game.md` | общие для проекта; fly-специфика из них вынесена (см. §5) |

---

## 2. Состояние линии на момент архивации (чтобы не пересказывать заново)

Пороги были объявлены **до** замера и не двигались: M1 `lvl ≥ 2`, M2 `kills ≥ 10`,
M3 `quests ≥ 5` за эпизод, M4 `travel ≥ 2.0`.

| Веха | Статус | Числа |
|---|---|---|
| M0 «живёт» | ✅ взята | reward `39.47`, 1 квест, шаг 724 |
| M1 «первый прогресс» | ❌ | уровень 1, 60 xp (в F8 `our` — level 2.60 в среднем, но это другой прогон) |
| M2 «боевой цикл» | ❌ | в F8 `our` kills 26.73 (порог взят), но deaths 5.07 при требовании «≤ 1 смерть» в `REMAINING.md` |
| M3 «квестовый цикл» | ❌ | **0 квестов во всех 85 эпизодах F8** |
| M4 «выход в мир» | ❌ | `travel_norm` признан непригодной метрикой: у мёртвых политик выше, чем у живой |

### F8 — последний результат линии (`fly-woc/outputs/benchmark_v3.json`)

6 условий × 3 сида × 5 эпизодов, полный эпизод 8000 шагов. Пересчитано независимо
из артефакта 2026-09-18:

| Условие | reward | kills | level | deaths | quests |
|---|---|---|---|---|---|
| `our` (fly-sampled) | **−0.189** | **26.73** | 2.60 | 5.07 | 0 |
| `er` (случайный граф той же плотности) | −4.381 | 7.67 | 1.60 | 2.40 | 0 |
| `rewired` (перепутанные связи) | −8.499 | 1.93 | 1.00 | 2.00 | 0 |
| `fly-argmax` / `silenced` / `untrained` | 0.000 | 0.00 | 1.00 | 0.00 | 0 |

Проведено **17 условий из 18**: отсутствует `untrained_s900201`, причина провала не
записана (дефект B7 ревью). Условия `mlp-sampled` нет совсем.

Честная формулировка вывода, которая была в доках: преимущество над контролями доказано
**по kills** и по относительному reward, но не по «reward > 0»; квестовый цикл не взят.

### Контроли воспроизводимы (проверено 2026-09-18)

```bash
cd archive/fly-line/fly-woc
python3 tools/make_control_graph.py --in data/circuit.json --out /tmp/er.json     --mode er     --seed 1   # 4.6 с
python3 tools/make_control_graph.py --in data/circuit.json --out /tmp/degree.json --mode degree --seed 1   # 13 с
```

Результат: графы **идентичны** закоммиченным `data/circuit_er.json` и
`data/circuit_rewired.json` по всем полям (`version/nodes/edges/inputs/outputs/channels/
input_types`), совпали и `swaps_applied=0`, `rejected_stubs=29743`.

Оговорка: `control.source_sha256` в закоммиченных файлах = `31254f5aaff660a7…`, а sha256
канона `fly-woc/data/circuit.json` = `3514c09808cc6aff…` (совпадает с `manifest.graphSha256`).
В истории репозитория у канона ровно одна версия (blob `2185007b`), то есть записанный
«источник» не указывает ни на один файл репо. Причина: генератор хеширует **сырые байты**
файла (`make_control_graph.py:132`), а не содержимое графа — контроли собрали из той же
схемы в другой сериализации. Дефект B8 ревью, не исправлен.

### Ключевые sha

| Артефакт | sha256 |
|---|---|
| каноническая схема `fly-woc/data/circuit.json` (8835 узлов / 1 874 865 рёбер) | `3514c09808cc6affaf044aaf7b242b9fe191c2539abd156d534302e42438384c` |
| полная таблица связей `data/circuit-full/circuit.json` (8836 / 1 874 492) | `3d90919e11863941aa5f173b21767407ebc3a48cd1e7f4ba707fcd85ae889bc9` |
| контроль `er` | `5f7b5e9f4c56f8fd00122c692982df3c245a78cf7561f0c553312ce698b8bd45` |

Данные MaleCNS (Janelia FlyEM и соавторы) — **CC BY 4.0**, атрибуция обязательна в
производных артефактах. Источник: `https://male-cns.janelia.org/download/`, публикация
данных 2026-06-08, статья Cell 2026-09-03. Хеши исходных `.feather` — в
`fly-woc/data/manifest.json`.

---

## 3. Как запустить проверки линии, если она понадобится снова

Нужны: Python 3.13, **torch** (в репозитории нет `requirements.txt` — ставить руками),
numpy 2.x, scipy, Node 20.x; для живых прогонов — чекаут игры в `WOC_PYTHON_PATH`.

```bash
cd archive/fly-line/fly-woc
bash tools/run_checks.sh                    # ожидаем: ВСЁ ЗЕЛЁНОЕ (8 блоков)
python3 tools/test_device.py                # 25+3 проверки выбора устройства
python3 tools/gpu_check.py --device cuda --bench          # на машине с картой
```

Проверено 2026-09-18 в песочнице (torch 2.14.0+cpu): `run_checks.sh` — 8/8 зелёные,
паритет бэкендов `max|Δ| = 2.98e-08` (edge) / `6.71e-08` (sparse), ускорение параллельных
сред 7.8x. **Без torch 4 блока из 8 падают** с `ModuleNotFoundError`.

---

## 4. Незакрытые дефекты линии (ревью 2026-09-18)

Если линию когда-нибудь разморозят — начинать с этого, а не с новых экспериментов.
Полный разбор: `REVIEW-world-of-claudecraft-agent.md` (воркспейс, не в репо).

| № | Что | Где |
|---|---|---|
| B1 | `progress_eval.py --mask-abilities` падает: `TypeError: ability_mask() got an unexpected keyword argument 'device'`. Две разошедшиеся копии функции; тесты импортируют копию из `train.py`, поэтому не ловят | `progress_eval.py:54` vs `:99` |
| B2 | `run_episode(max_steps)` параметр не использует: цикл `while True` до term/trunc. Все 85 эпизодов F8 шли 8000 шагов при `meta.max_steps = 1200` | `progress_eval.py:68` |
| B3 | `train.py` **хардкодит** `"env_version": {"obs": 607, "actions": 61}` в метаданные бенчмарка, хотя obs измерен рядом | `train.py:621` |
| B4 | `benchmark_v3.json` потерял `env_version`/`circuit`/`action_names`/`eval_config`, которые были в v2 и m1–m3 — главный артефакт описан хуже промежуточных | `f8_launch.py:46-49` |
| B5 | `--oracle-obs` молча не работает с политикой по умолчанию `fly-sampled` (нужно `policy == "fly"`) — тихий no-op | `progress_eval.py:188` |
| B6 | `f8_runner.py` нерабочий: пути дают `fly-woc/fly-woc/outputs/…`, `ckpt.exists() else None` → тихий прогон со случайными весами, политика `fly-sampled-silenced` не существует. Артефакт F8 собран `f8_launch.py` | `f8_runner.py:5,19,25,37-38` |
| B7 | `f8_launch.py` при провале подпроцесса пишет только в stdout: в артефакте нет ни отметки, ни причины | `f8_launch.py:35-38` |
| B8 | провенанс контролей записан байтовым sha источника, который не совпадает с каноном | `make_control_graph.py:132` |
| B13 | ~25 хардкодов `D:/…` в 15 файлах + дефолт чужой песочницы | `progress_eval.py:28`, `train.py:40`, `f8_launch.py:9,24` и др. |

Долги из `fly-woc/ROADMAP.md`, которые так и не закрыты: F6 (LIF вместо leaky-tanh),
F7 (каналы по типам клеток), F9 (M1–M3 на GPU), F10 (A/B «узкое плечо», потерян коммит
`2ae5aa5`), F11 (раздел «отрицательные результаты»).

---

## 5. Что изменено вне архива в связи с переносом

| Файл | Что сделано |
|---|---|
| `README.md` | одна активная линия; команды мухи убраны; добавлен указатель на архив |
| `AGENTS.md` | убрано противоречие «Java активна / fly на паузе»; fly-разделы заменены ссылкой на архив |
| `GIT-WORKFLOW.md` | `fly-woc/push_fixes.sh` → `tools/push_backup.sh` |
| `knowledge/README.md`, `verification.md`, `pitfalls.md`, `principles.md` | fly-строки вынесены сюда, общий протокол остался |
| `hermes/TOOLS.md` | таблица fly-линии вынесена в `archive/fly-line/TOOLS-fly.md` |
| `hermes/hooks/guard.sh`, `selftest.sh`, `task_end.sh`, `session_start.sh` | fly-предохранители и проверки заменены на правила для архива (не трогать/не удалять) |
| `hermes/skills/woc-master-goal/SKILL.md` | вторая половина цели («доказать против контролей rewired/er/MLP») относилась к мухе — переписана под Java-линию |
| `woof-agent/ROADMAP.md` | раздел «Fly-линия» заменён ссылкой на архив |
| `woof-agent/DEPENDENCIES.md` | убраны переменные окружения fly-линии |
| `.gitignore` | вычищен (~100 строк от чужого проекта), добавлен блок «Архив fly-линии»: тяжёлые данные архива сняты с отслеживания, код/доки/доказательства — в git |

Правило проекта сохранено: **знание не удаляется**. Отрицательные результаты
(`travel_norm` непригоден, `mlp-sampled` не записан, M3 = 0 квестов) остались в этом
файле и в `fly-woc/outputs/README.md`, `REMAINING.md`, `GITHUB-AUDIT.md`.
