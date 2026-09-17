# Статья Google про муху: где опубликована, как в неё зайти и что внутри

Дата разбора: 2026-09-17. Заказ: «проникни в гугл, где они опубликовали статью про муху».
Всё, что ниже, получено легально: официальные страницы Google, открытый препринт и датасет
под CC-BY. Обхода подписок не делалось.

---

## 0. Ответ в трёх строках

1. **Публикация Google** — это пост в блоге Google Research «A connectomics milestone: Mapping
   the complete male fruit fly brain» (3 сентября 2026, авторы **Michał Januszewski** и
   **Viren Jain**, Google Research). Именно он указывает на научную статью.
2. **Научная статья** — «Sexual dimorphism in the complete connectome of the *Drosophila* male
   central nervous system», журнал **Cell**, том 189, стр. 5504–5526.e15,
   DOI **10.1016/j.cell.2026.08.015**; 111 авторов (Janelia FlyEM + Кембридж + MRC LMB +
   Google Research, Цюрих).
3. **Полный текст открыт** в препринте bioRxiv **10.1101/2025.10.09.680999v2** — он скачан
   целиком и лежит в этой же папке разбора. Версия в Cell закрыта лицензией Elsevier, а
   сам сайт cell.com из песочницы отдаёт 403 (антибот), так что рабочий вход — препринт.

**И главное для нас:** это ровно тот датасет, на котором построен наш проект. Наш
`data/circuit.json` (8 835 узлов) — подграф этих 166 691 нейронов, а сцена Neuroglancer
`gs://flyem-male-cns/v1.0/male-cns-v1.0.json`, которую мы крутим на :8791, — официальная
сцена этой же работы.

---

## 1. Четыре входа Google: что отвечает, что нет

| Слой | Ожидалось | Фактически | Статус |
|---|---|---|---|
| `research.google/blog/…male-fruit-fly-brain/` | пост Google Research | открыт, текст получен полностью (3 фрагмента), есть блок Quick links на статью и датасет | OK |
| `blog.google/…male-fruit-fly-brain-map/` | новостной пост Google | открыт: «5 amazing visuals…», 166 000+ нейронов, ~11 700 типов, AI-склейка 2D-срезов | OK |
| `sites.research.google/gr/neural-mapping/` | хаб коннектомики Google | открыт: хронология 1986 (червь, 302 нейрона) → 2020 (hemibrain) → 2021 (H01, 1.4 ПБ) → 2023 (мышь) → 2026 (муха) | OK |
| Статья в **Cell** (DOI) | первоисточник | DOI резолвится, метаданные получены (Crossref/PubMed 42691995); `cell.com` из песочницы — **403**, `linkinghub` — JS-редирект без текста | доступен только через препринт |
| Препринт **bioRxiv v2** | открытая версия рукописи | скачан: HTML 1.3 МБ, из него извлечён текст (41 096 слов, 1 442 строки) | OK |
| Полнотекстовые базы | PMC / Europe PMC | PubMed есть, но Europe PMC: «Subscription required», PMCID нет | нет |

---

## 2. Что именно в статье (числа проверены по тексту препринта)

| Величина | Значение | Откуда |
|---|---|---|
| Нейронов в CNS | **166 691** (блог Google округляет до «более 166 000») | abstract препринта |
| Что входит | центральный мозг + обе оптические доли + вентральный нервный тяж (аналог спинного), с целым шейным коннективом | Janelia |
| Типов клеток | **11 691** | abstract |
| Синапсов | ~**125 млн** | блог Google |
| Сравнение полов (на синаптическом разрешении) | **7 205 изоморфных**, **114 диморфных**, **262 только-самец**, **69 только-самка** типов | abstract |
| Доля центрального мозга | 4.8 % у самца и 2.4 % у самки | Results |
| Главный вывод | полоспецифичные и диморфные нейроны сосредоточены в высших центрах, периферия почти изоморфна; диморфизм распространяется по всему мозгу через диморфные связи; «переключатели» цепей направляют один и тот же сенсорный поток в антагонистические схемы поведения | abstract/Results |
| Аннотации экспрессии | *fruitless* / *doublesex* — есть, и они хорошо (но не идеально) совпадают со статусом диморфизма | Results |

**Сопутствующие работы того же дня:** зрение — 10.1016/j.cell.2026.08.014, вкус —
10.1016/j.cell.2026.08.016, социальное поведение — 10.1016/j.cub.2026.08.013. Рядом:
полная ЦНС самки в *Nature* (10.1038/s41586-026-10735-w), рыба-слонорыл в *Nature*
(10.1038/s41586-026-10690-6), ZAPBench (активность личинки зебровой рыбки), реконструктор
**PATHFINDER** (bioRxiv 2025.05.16.654254).

---

## 3. Датасет: как скачать и что из него уже лежит у нас

Лицензия — **CC-BY 4.0**, то есть брать можно, но с атрибуцией. Публично доступно:

| Данные | Размер | Где |
|---|---|---|
| Аннотации нейронов (типы, стороны, классы) | 13 МБ | `body-annotations-male-cns-v1.0-minconf-0.5.feather` |
| Нейромедиаторы | 42 МБ | `body-neurotransmitters-male-cns-v1.0.feather` |
| Статистика по сегментам | 780 МБ | `body-stats-…feather` |
| **Полный граф связей** | 1.1 ГБ | `connectome-weights-male-cns-v1.0-minconf-0.5.feather` |
| Синапсы (точки) | 12.7 ГБ | `syn-points-…feather` |
| Пары синапсов | 6.8 ГБ | `syn-partners-…feather` |
| Скелеты SWC / precomputed, в т.ч. шаблон JRC2018 | — | `gs://flyem-male-cns/v1.0/segmentation/skeletons-*` |
| Готовый neo4j для своего neuPrint | — | `gs://flyem-male-cns/v1.0/database/neo4j` |

Быстрые входы: **neuPrint** `?dataset=male-cns:v1.0` (+ `neuprint-python`, R-пакет `malecns`),
**Clio**, **MaleCNS Cell Type Explorer**, **NeuronBridge**, **Neuroglancer** (сцена та же,
что у нас), **male-cns.janelia.org** — сравнение диморфных клеток самца и самки.

**Что из этого уже у нас в проекте:**
`fly-woc/data/circuit.json` — 8 835 узлов (**5.3 %** этого CNS) и 1 874 865 рёбер,
`nodes[].id` — это MaleCNS `bodyId`; файл аннотаций —
`body-annotations-male-cns-v1.0-minconf-0.5.feather` (у нас 14.5 МБ, **211 577 строк**,
**11 752** уникальных типа, sha256 `2177e246…`) — то есть физически тот же опубликованный
артефакт, и в нём типов даже чуть больше, чем «11 691» из abstract (там считаются
типы нейронов, а в файле ещё служебные категории).

---

## 4. Что скачано локально (офлайн, без сети)

| Файл | Что это | Размер |
|---|---|---|
| `google-fly/preprint-v2.md` | **текст статьи**: Abstract, Introduction, Results (полный коннектом, поток сенсорики→моторики, зрение/слух/обоняние/вкус, топология диморфизма, генетическая база), Discussion, Methods, Data availability | 267 КБ, 41 096 слов |
| `google-fly/preprint-v2.html` | страница препринта как она есть (со ссылками и рисунками) | 1.3 МБ |
| `fly-woc/GOOGLE-FLY.md` | этот разбор | — |

PDF препринта скачать не удалось: bioRxiv отдаёт из песочницы **429** (антибот-лимит на
дата-центры), стандартный обход — вручную из браузера. На содержание это не влияет: HTML
содержит полный текст.

---

## 5. Честные границы «проникновения»

1. **403 от cell.com — это антибот, а не пейволл.** OpenAlex помечает статью как `hybrid` OA
   (`is_oa=true`), то есть из обычного браузера она, скорее всего, читается. Из песочницы
   Elsevier блокирует автоматические запросы.
2. **Мы не обходили подписку** и не пользовались зеркалами: препринт — официальная открытая
   версия той же рукописи, датасет — CC-BY.
3. **Тираж цифр:** «166 000 + / 125 млн» — из блога Google (округление), точные значения из
   abstract — 166 691 нейрон и 11 691 тип; 125 млн синапсов в препринте не оспаривается,
   но в самом тексте фигурирует как «~125 млн» в сводках.
4. **Наш коннектом ≠ их коннектом.** Мы работаем с подграфом 8 835 нейронов, и всё, что мы
   измеряем (в том числе связка «LLM в мозгу»), относится к нему, а не к полному CNS.

---

## 6. Прямые ссылки

**Google**
- Пост Google Research: https://research.google/blog/a-connectomics-milestone-mapping-the-complete-male-fruit-fly-brain/
- Новостной пост Google: https://blog.google/innovation-and-ai/technology/research/male-fruit-fly-brain-map/
- Хаб коннектомики: https://sites.research.google/gr/neural-mapping/
- Видео: https://www.youtube.com/shorts/HD9cDLgSe-o

**Статья**
- Cell (DOI): https://doi.org/10.1016/j.cell.2026.08.015 (PII S0092867426009426, PubMed 42691995)
- Открытый препринт: https://www.biorxiv.org/content/10.1101/2025.10.09.680999v2
- Пресс-релиз Janelia: https://www.janelia.org/news/researchers-reveal-connectome-of-the-male-fruit-fly-central-nervous-system
- Страница данных Janelia: https://www.janelia.org/project-team/flyem/male-cns-connectome
- Сайт датасета: https://male-cns.janelia.org/ · скачивание: https://male-cns.janelia.org/download/
- Сравнение диморфизма: https://male-cns.janelia.org/build/dimorphism_overview/
- neuPrint: https://neuprint.janelia.org/?dataset=male-cns%3Av1.0
- Neuroglancer (та же сцена, что у нас): https://neuroglancer-demo.appspot.com/#!gs://flyem-male-cns/v1.0/male-cns-v1.0.json
- Explorer типов клеток: https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/ · Clio: https://clio.janelia.org/

**Сопутствующие**
- Зрение: https://doi.org/10.1016/j.cell.2026.08.014 · Вкус: https://doi.org/10.1016/j.cell.2026.08.016 ·
  Поведение: https://doi.org/10.1016/j.cub.2026.08.013
- ЦНС самки: https://www.nature.com/articles/s41586-026-10735-w · Рыба: https://www.nature.com/articles/s41586-026-10690-6
- PATHFINDER: https://www.biorxiv.org/content/10.1101/2025.05.16.654254v1
- Датасет FlyWire (самка): https://flywire.ai/
