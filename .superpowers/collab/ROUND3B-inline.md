# Раунд 3-бис: только решения (весь код уже прочитан за тебя)

В прошлый раз ты упёрся в лимит итераций, читая файлы. Ниже — все нужные
выдержки кода СРАЗУ. Ничего читать не надо, отвечай сразу решениями.

## Факты измерений (пост-фикс прогон, 171 шаг)

```
heal 53 (31%), cast_frostbolt 29, gather 25, farm 23, cast_fireball 21, loot 20
turn_in_quest: 0     return_to_giver: 0
gather: 25 попыток -> ВСЕ 25 = inconclusive
deaths/1000 = 5.8 (приёмка <=2.0)
qprog 12->12 (не двинулся)
```

CDP-зонд на живом мире:
```json
{"playerPos": [-13, 275], "corpses": [], "hasHarvestCorpse": "function"}
```
Трупов в радиусе 40yd — НОЛЬ. API харвеста рабочий.

## Код: как gather попадает в кандидаты (policy.py:280-285)

```python
quest_collect_pending = any(
    (qq.get("id") or "").startswith("q_prof_workorder")
    for qq in (active + ready))
if quest_collect_pending and inv_map:
    if SKILL_GATHER not in cands:
        cands.append(SKILL_GATHER)
```
Предусловия «есть узел/труп рядом» — НЕТ.

## Код: исполнение gather (src/bridge/actions.cjs, case 5)

```js
case 5: { // gather: node first; else harvest a fresh beast/spider corpse
  const nodeId = await gameClient.evaluate(() => { /* ищет gather_node в 60yd */ });
  if (nodeId != null) { await ...harvestNode(String(nodeId)); break; }
  // нет узла -> ищем труп с componentTags в 30yd
  const corpseId = await gameClient.evaluate(() => {
    for (const e of sim.entities.values()) {
      if (e.kind !== 'mob' || !e.dead) continue;
      const tags = e.componentTags || [];
      if (!tags.length) continue;
      /* ближайший в 30yd */
    }
  });
  if (corpseId && corpseId.id != null) {
    await ...harvestCorpse(Number(corpseId.id), corpseId.tags);
  }
  break;   // <-- если ни узла, ни трупа: тихий no-op, мир не меняется
}
```

## Код: верификатор gather (verifiers_py.py:140-151)

```python
def verify_gather(c):
    h = c.get('handle') or {}
    node_id = h.get('nodeId'); mat_id = h.get('materialId')
    nb = _node_by_id(c['before'], node_id); na = _node_by_id(c['after'], node_id)
    consumed = nb and nb.get('harvestable') and not (na and na.get('harvestable'))
    mb = _item_count(c['before'], mat_id) if mat_id else _inv_total(c['before'])
    ma = _item_count(c['after'], mat_id) if mat_id else _inv_total(c['after'])
    if consumed and ma > mb: return 'success'
    if ma > mb: return 'success'
    return 'inconclusive'      # <-- нет объекта = inconclusive, НЕ failure
```

Следствие: 25 шагов в пустоту, reward≈0, Q ничему не учится (inconclusive
не наказывается), и агент может повторять это бесконечно.

## Код: детерминированный override логистики (policy.py:430-441)

```python
if goal == "RETURN_TO_GIVER" and ws.get("hp_frac", 1.0) >= 0.35 \
        and SKILL_RETURN in cands:
    return SKILL_RETURN, self._turn_ctx(info, SKILL_RETURN)
if goal == "TURN_IN" and ws.get("hp_frac", 1.0) >= 0.35 \
        and SKILL_TURN_IN in cands:
    return SKILL_TURN_IN, self._turn_ctx(info, SKILL_TURN_IN)
```

## Вопросы — отвечай сразу, код читать не нужно

**Q5. Precondition-гейт.** Три варианта:
(а) не включать скилл в кандидаты без объекта действия (риск: не пробуется, не учится);
(б) включать, но при отсутствии объекта вердикт = `failure`, не `inconclusive`
    (Q научится не тратить шаги; риск: наказываем за отсутствие объекта, а не за плохое решение);
(в) гибрид: предусловие как фильтр + разведочный бюджет (раз в N шагов пробовать вопреки фильтру).
Твой выбор + что сломается.

**Q6. Дрейф позиции.** Агент на `[-13, 275]`, вдали от мобов, гиверов и узлов.
Нужен «домашний якорь» (возврат в рабочую зону, когда рядом нет объектов
действий), или это должно решаться safe-anchors из шага #6? Если якорь —
как выбирать точку: последняя позиция с мобами? позиция гивера активного
квеста? центр зоны?

**Q7. Метрика шага #1.** Твоя была «turn_in попыток > 0 за 200 шагов» — не
выполнена (0), но по объективной причине: ни один квест не дошёл до READY.
Предлагаю заменить на: (1) юнит-тест «return_to_giver в кандидатах при
goal∈{RETURN_TO_GIVER,TURN_IN} и hp≥0.35» — уже зелёный; (2) «gather
попыток > 0» — выполнено (25). Согласен?

**Q8. Что следующим?** Варианты: (A) шаг #2 из плана (детерминизация
логистики + награда только по verify); (B) сначала precondition-гейты и
дрейф позиции, потому что агент тратит шаги на действия без объектов;
(C) сначала сокращение сетки Q (шаг #4). Выбери один и обоснуй числом.

## Формат

JSON: `answers` (Q5-Q8 с полями question/answer/reasoning/risks),
`revised_order` (шаги с метриками), `risk_notes`, `disagreements`.
Отвечай КОРОТКО и по делу — у тебя лимит итераций, не трать его на чтение.
