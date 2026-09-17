# Экосистема MaleCNS: что брать, откуда и на каких условиях

Срез на 2026-09-17. Источник обзора — список [cobanov/awesome-fly](https://github.com/cobanov/awesome-fly)
(его ведёт автор Fly Dino; в нём же оговорено: «это обзор документации, а не независимые
воспроизведения»). Лицензии проверены через GitHub API, а не по обещаниям в README.

---

## 1. Что берём — по нашим задачам

| # | Наша задача (из REMAINING.md) | Источник | Лицензия | Что именно берём |
|---|---|---|---|---|
| 1 | **LIF вместо leaky-tanh** | [alextitonis/fly.ai](https://github.com/alextitonis/fly.ai) — пакет `flybrain` на PyPI | MIT ★82 | референс динамики: LIF по всему MaleCNS, dt 20 мс, рефрактерность, batch, `brain.cells([...], side=)`, `brain.step(inject=[(idx, amount)])`; как эталон для сверки **нашего** LIF |
| 2 | **Rewired/matched-контроль** | метод — [FlyDoom](https://github.com/eganeganegan/flydoom); постановка — [nfly](https://github.com/zhengxuyu/nfly)/[FlyBlox](https://github.com/Sir-Monke/FlyBlox) | у FlyDoom лицензии **нет** → только метод; nfly MIT | сделано **своими руками**: `tools/make_control_graph.py` (обмен рёбер + ER), см. §4 |
| 3 | **Новые входные каналы, пересборка circuit.json** | fly.ai (`brain.cells(type, side)`), [connectome-interpreter](https://github.com/YijieYin/connectome_interpreter), [connectome_data_prep](https://github.com/YijieYin/connectome_data_prep) | MIT; у двух последних лицензии нет → только идеи/данные | адресация нейронов **по типу клетки**, а не по индексу: устойчиво к пересборке схемы; манипуляции подграфом (k-hop, топ-связность) |
| 4 | **Формат приёмки и контролей** | [fly-craftax](https://github.com/liuzihe02/fly-craftax) | MIT | дисциплина `make eval / make controls`: zero-shot против абляций, калибровка (lamina bias, вес синапса), MN9-проверка против Shiu et al., brain-only bench, scrubbable viewer |
| 5 | **Отрицательные результаты как обязательный раздел** | [doomfly](https://github.com/nftechie/doomfly) (MIT), [FLYT3](https://github.com/seanphan/flyt3) (без лицензии), [neuroterrarium](https://github.com/5p00kyy/neuroterrarium) (MIT) | см. | шаблон честности: у них прямо написано, что не сработало; нам такой раздел нужен по умолчанию |
| 6 | **Полный граф и производительность** | [Fly.exe](https://github.com/Ibtisam-Mohammad/Fly.exe) (**GPL-2.0**), FastFly, `mps-malecns-model` | GPL / нет | только инженерные приёмы: hashed-массивы вместо dense, проверка по контрольной сумме при загрузке, «неразрешённые знаки обнуляем, а не угадываем» |
| 7 | **Визуализация и дашборд** | [FalinX/fly-brain](https://github.com/FalinX/fly-brain) (README: MIT), [cobanov/fly-connectome-template](https://github.com/cobanov/fly-connectome-template) | MIT / **custom: кредит обязателен** | three.js-облако точек, живой HUD, скраббинг; soma-атлас для рендера нейронов |
| 8 | **Метаданные и сверка типов клеток** | [2025malecns](https://github.com/flyconnectome/2025malecns), [celltype-explorer](https://github.com/reiserlab/celltype-explorer-drosophila-male-cns), [neuprint-python](https://github.com/connectome-neuprint/neuprint-python), [cocoa](https://github.com/flyconnectome/cocoa), [navis](https://github.com/navis-org/navis) | данные — CC BY 4.0 | сенсоримототорный поток, сопоставление типов, доступ к neuPrint (`male-cns:v1.0`) |

---

## 2. Что у нас уже есть — не тянем заново

| Что | Где у нас | Комментарий |
|---|---|---|
| LIF-динамика (conductance) | `src/fly_brain/engine.py` | tauSyn 5 мс, tauMem 10 мс, рефрактерность, буфер задержки — **готовый LIF**, а активная линия `fly-woc` всё ещё считает leaky-tanh. Замена динамики — это перенос своей же реализации, а не импорт чужой |
| Brian2-обёртка Shiu et al. | `src/fly_brain/connectome_philshiu.py` | v_th −45 мВ, tau 5 мс; эталон для сверки |
| Дашборд | `src/fly_brain/connectome_dashboard.py` | база под живой HUD |
| Оракул квестов | `fly-woc/quest_oracle.py` + таблицы 204/214/224 | такого нет ни у кого в экосистеме — наша часть |
| Контроли silenced/untrained/sampled | `fly-woc/train.py` | плюс теперь rewired/ER |

---

## 3. Лицензионная гигиена (что можно и что нельзя)

| Категория | Репозитории | Правило |
|---|---|---|
| Пермиссивные (MIT / Apache-2.0) | fly.ai, fly-craftax, doomfly, nfly, philshiu, flybody, flygym | код можно брать с указанием авторства и лицензии |
| **GPL-2.0** (копилефт) | Fly.exe, eonsystemspbc/fly-brain | код копировать нельзя, если проект не станет GPL-совместимым. Берём идеи/протоколы; Brian2 — отдельная библиотека, её ставить можно |
| **Без лицензии = все права защищены** | FlyDoom, FLYT3, FlyBlox, fly-chess, connectome_data_prep | код не копируем даже частично. У FlyDoom нет лицензии, а он ближе всех к нашей задаче → поэтому rewired-контроль реализован нами с нуля |
| Данные MaleCNS | male-cns.janelia.org | **CC BY 4.0**: атрибуция обязательна в производных артефактах, фигурах и отчётах |
| Custom | fly-connectome-template | кредит обязателен в UI и README |
| «Vibe coded» | fly64 (ornata/fly) и подобное | читать можно, брать код — нет смысла: ни метрик, ни контролей |

**Правило для нас:** любое заимствование — с указанием репозитория, лицензии и того, что именно взято.
Данные MaleCNS цитируем (Berg et al., Cell 2026; датасет — 8 июня 2026, статья — 3 сентября 2026).

---

## 4. Что сделано прямо сейчас

`fly-woc/tools/make_control_graph.py` + `tools/test_control_graph.py` (коммит `b329908`, ветка `backup` локально):

* `--mode degree` — обмен рёбер: in/out-степени **каждого** узла сохраняются точно, граф остаётся
  простым, вес остаётся на своём ребре (профиль исходящих весов нейрона цел — критично, потому что
  нормализация идёт по контактам: `W[j,i] = c·s[j] / Σ_k c·|s[k]|`);
* `--mode er` — Эрдёш–Реньи с теми же N и M, петли исключены, мультимножество весов то же;
* сохраняются узлы (`type/side/nt/sign/role`) и раскладки (`inputs/outputs/channels/input_types`);
* в файл пишется блок `control` с sha источника, seed, числом обменов и результатами проверок.

Проверено (`python3 tools/test_control_graph.py --full`): синтетика с петлями, детерминизм по seed,
«swaps=0 = исходник», подграф 400 узлов и **полная схема** 8835 / 1.87M (degree: изменено 39.4 %
пар при 25 % обменов, петли 7→7; er: 100 % пар, петли 7→0). Все четыре набора проверок в
`tools/run_checks.sh` зелёные.

Кстати, по дороге выяснилось важное про нашу схему: веса в `circuit.json` — это **счётчики контактов**
(1…1601, все положительные), а знак берётся от пресинаптического нейрона. То есть 36 % рёбер
«не согласованы со знаком узла» не ошибка: знак просто живёт в узле, а не в ребре. Контроль это
сохраняет — иначе он был бы контролем чего-то другого.

---

## 5. Честный сигнал экосистемы (важно для наших заявок)

| Проект | Что показал | Урок для нас |
|---|---|---|
| doomfly (Wormuth, ★323) | дофаминовый контур (стимуляция двух PPL101 при уроне), стрим, но: **«learned survival has not been demonstrated»**, есть раздел отрицательных проверок; по прессе — 3000 прогонов без роста выживаемости | демо ≠ обучение; наш M0/M1 — та же стена, и мы её честно назвали порогами |
| FLYT3 | собственный негативный контроль: MLP на тех же входах **85.7 %** против коннектома **60.8 %** | вопрос «коннектом лучше MLP?» зададут первым |
| neuroterrarium, FlyPong | негативные результаты по топологическому контролю и дофаминовой пластичности | если у нас rewired покажет то же — это результат, а не провал |
| FalinX/fly-brain | ridge-readout по 1314 DN поднял попадание 66.6 %→78.5 %, **но игру сделал хуже**: readout обучен на состояниях другого контроллера | не переносить readout между версиями/контроллерами; пары «энкодер+readout» не смешивать |
| fly-craftax | нулевой выстрел против абляций, калибровка, проверка против Shiu et al. | наш аналог — обязательный прогон против rewired/ER/silenced **теми же сидами** |

Вывод: **M3 (≥5 квестов за эпизод) в опенсорсе не показал никто.** Ниша «коннектом проходит RPG-квесты
через RL» действительно свободна. Но и «коннектом полезнее своей перепутанной копии» пока не
доказано — теперь у нас есть инструмент, чтобы это проверить самим.

---

## 6. План внедрения (по шагам)

1. **Контроли топологии** — сделано (`b329908`); прогнать `--mode degree/er` на полной схеме и
   положить sha-controls рядом с sha схемы.
2. **LIF вместо leaky-tanh**: в `fly-woc/fly_brain.py` заменить `h_new = 0.3h + 0.7·tanh(...)` на
   LIF из `src/fly_brain/engine.py`; сверить с `pip install flybrain` (MIT, ~260 МБ данных) на одном
   и том же входе по статистике активности DN. Критерий: совпадение распределений в пределах допуска,
   иначе — публикуем расхождение.
3. **Каналы по типам клеток**: заменить список индексов `inputs` на адресацию `brain.cells([...], side=)`,
   пересобрать `circuit.json` с новыми `CHANNEL_TYPES`; старую схему (sha `3514c098…`) сохранить для
   сравнения.
4. **Приёмка**: отчёт «наш / rewired / ER / MLP / silenced / untrained» по 3 сидам, пороги M1–M4 из
   `progress_eval.py` — объявлены заранее и не меняются после замера.
5. **M1–M3 прогон** на машине с GPU: `tools/accel_m1_m3.sh` (ступени check → smoke → probe → main).

---

## 7. Проверенные ссылки

Игры/контроллеры: [doomfly](https://github.com/nftechie/doomfly) · [FlyDoom](https://github.com/eganeganegan/flydoom) ·
[Fly64](https://github.com/ornata/fly) · [fly-craftax](https://github.com/liuzihe02/fly-craftax) ·
[Fly Dino](https://github.com/cobanov/flyjump) · [FLYT3](https://github.com/seanphan/flyt3) ·
[FlyPong](https://github.com/jonatasperaza/FlyPong) · [fly-chess](https://github.com/tolatolatop/fly-chess) ·
[fly-escape](https://github.com/dzhng/fly-escape) · [neurocraft-fly](https://github.com/evnsnclr/neurocraft-fly-public)
(релиз кода ещё не выложен) · [neuroterrarium](https://github.com/5p00kyy/neuroterrarium) ·
[FlyBlox](https://github.com/Sir-Monke/FlyBlox) · [nfly](https://github.com/zhengxuyu/nfly)
Движки и модели: [fly.ai / flybrain](https://github.com/alextitonis/fly.ai) · [eonsystemspbc/fly-brain](https://github.com/eonsystemspbc/fly-brain) (GPL-2.0) ·
[philshiu/Drosophila_brain_model](https://github.com/philshiu/Drosophila_brain_model) · [Fly.exe](https://github.com/Ibtisam-Mohammad/Fly.exe) (GPL-2.0) ·
[flybody](https://github.com/TuragaLab/flybody) · [flygym](https://github.com/NeLy-EPFL/flygym) · [FalinX/fly-brain](https://github.com/FalinX/fly-brain)
Данные и инструменты: [male-cns.janelia.org](https://male-cns.janelia.org/) · [2025malecns](https://github.com/flyconnectome/2025malecns) ·
[celltype-explorer](https://github.com/reiserlab/celltype-explorer-drosophila-male-cns) · [neuprint-python](https://github.com/connectome-neuprint/neuprint-python) ·
[cocoa](https://github.com/flyconnectome/cocoa) · [navis](https://github.com/navis-org/navis) · [connectome-interpreter](https://github.com/YijieYin/connectome_interpreter)
Обзор: [cobanov/awesome-fly](https://github.com/cobanov/awesome-fly) (туда же потом PR — после M3)
