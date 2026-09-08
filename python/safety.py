"""safety.py — Safety gate for the arbitration layer.

Single responsibility: detect life-threatening states and return
the ONLY safe action. No learning, no overrides — pure safety.

Priority 1 in the unified decision hierarchy:
  1. SAFETY  → death/critical HP → respawn/heal/noop
  2. RECOVERY → stuck/loop → recovery skill
  3. POLICY  → softmax over candidates (Q-learning)
  4. PLANNER → advisor only (context, not force)
  5. FSM     → execution state machine (phase label only)
"""
import re
from typing import Optional

# Чем в этой игре реально лечатся: зелья и еда. game_meat/rough_hide — сырьё
# профессий (src/sim/content/profession_items.ts), heal на них — no-op.
_HAS_HEAL_PAT = re.compile(r"potion|draught|tonic|elixir|heal|bread|water|jerky"
                           r"|roasted|cooked|meal|ration|cheese|apple", re.I)


def _has_healing(info: dict, ws: dict) -> bool:
    """Есть ли в сумках то, чем heal сработает. Нет данных -> считаем что нет.

    P0.10: читаем ОБА имени. world_state кладёт словарь как `inv_by_id`,
    мост — как `inventory_by_id` в info. Раньше читалось только второе, и
    heal работал лишь потому, что поле приходило из моста: любой вызов с
    canonical ws без мостового поля терял heal полностью (та же поломка,
    что junk в P0.1 — разъехавшееся имя превращает предикат в вечный False).
    """
    items = None
    for src in (info, ws):
        if not isinstance(src, dict):
            continue
        for key in ("inventory_by_id", "inv_by_id"):
            cand = src.get(key)
            if isinstance(cand, dict) and cand:
                items = cand
                break
        if items is not None:
            break
    if not isinstance(items, dict) or not items:
        return False
    return any(_HAS_HEAL_PAT.search(str(k)) for k, v in items.items() if (v or 0) > 0)


def safety_check(info: dict, ws: dict) -> Optional[str]:
    """Return forced action if safety requires it, else None.

    Returns:
        "respawn"   if player dead
        "heal"      if hp < 0.2 AND has potions/food
        "noop"      if hp < 0.2 AND no potions (wait for regen)
        None        if safe to proceed
    """
    player = info.get("player") or {}
    if player.get("dead"):
        return "respawn"

    hp_frac = ws.get("hp_frac", 1.0)
    if hp_frac < 0.2:
        if _has_healing(info, ws):
            return "heal"
        return "noop"  # wait for regen, don't waste actions

    return None
