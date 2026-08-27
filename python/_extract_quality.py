"""Механически извлекает quality из woc-game/src/sim/content/items.ts.

Дописывает поле "quality" в item_prices.json. НЕ выдумывает значения:
берёт только то, что реально объявлено в исходниках игры.
"""
import io
import json
import os
import re

ITEMS_TS = r"D:/woc-game/src/sim/content/items.ts"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "item_prices.json")

with io.open(ITEMS_TS, encoding="utf-8") as f:
    src = f.read()

# Каждое определение предмета начинается с `id: '...'`; quality объявлен внутри
# того же объекта. Режем по id и ищем ближайший quality до следующего id.
ids = [(m.start(), m.group(1)) for m in re.finditer(r"\bid:\s*'([a-z0-9_]+)'", src)]
found = {}
for i, (pos, item_id) in enumerate(ids):
    end = ids[i + 1][0] if i + 1 < len(ids) else len(src)
    chunk = src[pos:end]
    q = re.search(r"\bquality:\s*'([a-z]+)'", chunk)
    if q:
        found[item_id] = q.group(1)

with io.open(OUT, encoding="utf-8") as f:
    prices = json.load(f)

added = 0
for item_id, quality in found.items():
    row = prices.get(item_id)
    if row is None:
        prices[item_id] = {"buy": None, "sell": None, "quality": quality}
        added += 1
    elif row.get("quality") != quality:
        row["quality"] = quality
        added += 1

with io.open(OUT, "w", encoding="utf-8") as f:
    json.dump(prices, f, ensure_ascii=False, indent=1, sort_keys=True)

by_q = {}
for q in found.values():
    by_q[q] = by_q.get(q, 0) + 1
print("извлечено quality:", len(found), "обновлено записей:", added)
print("распределение:", json.dumps(by_q, ensure_ascii=False))
print("poor:", sorted(k for k, v in found.items() if v == "poor"))
