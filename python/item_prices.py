"""item_prices.py — цены предметов ИЗ ИСХОДНИКОВ игры (P0.4).

Источник: woc-game/src/sim/content/items.ts (buyValue / sellValue).
Извлечены механически в item_prices.json; это НЕ выдуманная таблица и НЕ
второй источник истины о состоянии мира — это справочник цен контента,
которого нет в снапшоте (модуль items не экспонирован в window).

Приоритет всегда за живыми данными: если снапшот отдал vendor_offers с
ценой, используется она.
"""
import io
import json
import os
from typing import Any, Dict, Optional

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "item_prices.json")

_PRICES: Dict[str, Dict[str, Optional[int]]] = {}
try:
    with io.open(_PATH, encoding="utf-8") as fh:
        _PRICES = json.load(fh)
except Exception:                      # справочника нет — работаем без него
    _PRICES = {}


def buy_price(item_id: str) -> Optional[int]:
    """Цена покупки в медяках, None если неизвестна."""
    rec = _PRICES.get(str(item_id or ""))
    return rec.get("buy") if isinstance(rec, dict) else None


def sell_price(item_id: str) -> Optional[int]:
    rec = _PRICES.get(str(item_id or ""))
    return rec.get("sell") if isinstance(rec, dict) else None


def price_from_snapshot(info: Dict[str, Any], item_id: str) -> Optional[int]:
    """Цена из ЖИВОГО снапшота (vendor_offers), если мост её дал."""
    vo = (info or {}).get("vendor_offers") or {}
    for it in (vo.get("items") or []):
        if isinstance(it, dict) and it.get("itemId") == item_id:
            p = it.get("price")
            if p is not None:
                return int(p)
    return None


def resolve_price(info: Dict[str, Any], item_id: str) -> Optional[int]:
    """Живая цена, иначе справочник контента. None = НЕИЗВЕСТНО."""
    live = price_from_snapshot(info, item_id)
    return live if live is not None else buy_price(item_id)


def vendor_sells(info: Dict[str, Any], item_id: str) -> Optional[bool]:
    """Есть ли товар у ближайшего вендора.

    Возвращает None когда ассортимент НЕИЗВЕСТЕН — вызывающий обязан
    трактовать None как «не подтверждено», а не как «есть» (fail-closed).
    """
    vo = (info or {}).get("vendor_offers")
    if not isinstance(vo, dict):
        return None
    items = vo.get("items")
    if not isinstance(items, list) or not items:
        return None
    return any(isinstance(it, dict) and it.get("itemId") == item_id
               for it in items)


# ---- quality / junk (P0.1) ----
# `quality` в игре — СТРОКА. Живой замер items.ts: poor 8, common 80,
# uncommon 65, rare 41, epic 7. Прежний детект сравнивал её с нулём и
# не срабатывал НИКОГДА, из-за чего sell_junk был заблокирован навсегда.
JUNK_QUALITIES = frozenset({"poor"})


def item_quality(item_id: str) -> Optional[str]:
    """Quality предмета из справочника контента. None = НЕИЗВЕСТНО."""
    row = _PRICES.get(item_id) if isinstance(_PRICES, dict) else None
    if not isinstance(row, dict):
        return None
    q = row.get("quality")
    return q if isinstance(q, str) and q else None


def is_junk_quality(quality: Any) -> bool:
    """True только для явного junk-качества.

    None / пусто / неизвестное значение -> False (fail-closed): отсутствие
    данных не повод продавать предмет.
    """
    if not isinstance(quality, str):
        return False
    return quality.strip().lower() in JUNK_QUALITIES


def is_junk_item(item_id: str, quality: Any = None) -> bool:
    """Хлам ли предмет: сначала живое quality из снапшота, затем справочник."""
    if isinstance(quality, str) and quality.strip():
        return is_junk_quality(quality)
    return is_junk_quality(item_quality(item_id))
