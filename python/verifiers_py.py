"""Python mirror of verifiers.ts (Phase C chains use this for honest checks).
Mirrors the TS logic exactly:
  verifyFarm / verifyLoot / verifyQuestAccept / verifyQuestTurnIn /
  verifySellJunk / verifyGather / verifyCraft / verifyHeal / verifyEquip / verifyBuy
Each returns 'success' | 'failure' | 'inconclusive'.
"""
from typing import Any


def _player_copper(w):
    # bridge puts copper at top-level info.copper (not under player.*)
    return w.get('copper', 0) or (w.get('player') or {}).get('copper', 0)
def _player_kills(w): return (w.get('player') or {}).get('kills', 0) or (w.get('kills', 0))
def _player_hp(w): return (w.get('player') or {}).get('hp', 0)
def _player_hp_max(w):
    # bridge snapshot emits player.maxHp; tolerate hpMax too for forward-compat
    return (w.get('player') or {}).get('maxHp') or (w.get('player') or {}).get('hpMax') or 1
def _junk_items(w):
    return [i for i in (w.get('inventory') or []) if (i.get('quality') or 0) == 0]
def _item_count(w, item_id=None):
    items = w.get('inventory') or []
    if not item_id:
        return len(items)
    return sum(i.get('count', 1) for i in items if i.get('itemId') == item_id)
def _inv_total(w): return len(w.get('inventory') or [])
def _corpse_exists(w, corpse_id=None):
    for e in (w.get('nearby') or []):
        if corpse_id is not None and e.get('id') != corpse_id:
            continue
        # unified corpse definition: explicit corpse kind/type OR a lootable dead
        # mob (the bridge forwards dead mobs as kind='mob', dead=true,
        # lootable=true — verifier must treat those as corpses).
        is_corpse = (e.get('type') == 'corpse' or e.get('kind') == 'corpse')
        is_lootable_mob = bool(e.get('lootable')) and (e.get('dead') or (e.get('kind') == 'mob' and e.get('lootable')))
        if (is_corpse or is_lootable_mob) and not e.get('looted'):
            return True
    return False
def _node_by_id(w, node_id):
    for n in (w.get('gather', {}).get('nearbyNodes') or []):
        if str(n.get('id')) == str(node_id):
            return n
    return None
def _quest_state(w, qid):
    qs = w.get('quests') or {}
    for bucket in ('active', 'ready'):
        for q in (qs.get(bucket) or []):
            if q.get('id') == qid:
                return q.get('state')
    if qid in (qs.get('done') or []):
        return 'done'
    if qid in (qs.get('available') or []):
        return 'available'
    return None
def _equip_slot(w, slot):
    return (w.get('player') or {}).get('equipment', {}).get(slot)


def verify_farm(c):
    """Objective combat verification for the ONLINE world.

    Server-authoritative `kills` does NOT always tick on a locally-driven white-hit
    kill, so using only kills_after > kills_before hides real learning signal. We
    therefore accept ANY honest evidence that the farm action produced a combat
    consequence:
      - server kills increased, OR
      - a mob that was alive (hp>0) before is now dead/lootable/gone, OR
      - a lootable corpse appeared that was not there before, OR
      - player XP increased (real consequence of a kill in this Sim).
    """
    b, a = c['before'], c['after']
    if _player_kills(a) > _player_kills(b):
        return 'success'
    # mob hp delta: any mob present before with hp>0 is now gone / dead / lootable
    before_mobs = {(e.get('id')): e for e in (b.get('nearby') or [])
                    if (e.get('kind') == 'mob' or e.get('type') == 'mob') and not e.get('lootable')}
    after_mobs = {(e.get('id')): e for e in (a.get('nearby') or [])
                   if (e.get('kind') == 'mob' or e.get('type') == 'mob')}
    for mid, me in before_mobs.items():
        if (me.get('hp') or 0) > 0:
            ae = after_mobs.get(mid)
            if ae is None or ae.get('dead') or ae.get('lootable'):
                return 'success'
    # a fresh lootable corpse appeared
    if _corpse_exists(a) and not _corpse_exists(b):
        return 'success'
    # xp gain (real kill consequence in this Sim)
    if (a.get('player') or {}).get('xp', 0) > (b.get('player') or {}).get('xp', 0):
        return 'success'
    return 'inconclusive'

def verify_loot(c):
    had = _corpse_exists(c['before'], c['handle'])
    delta = _inv_total(c['after']) - _inv_total(c['before'])
    if had and delta > 0:
        return 'success'
    if had and not _corpse_exists(c['after'], c['handle']):
        return 'success'
    return 'inconclusive'

def verify_quest_accept(c):
    if not c['handle']:
        return 'inconclusive'
    # server contract (verified 2026-08-16): accept_quest puts the quest
    # directly into quests.active (state 'active'), NOT via an 'available'
    # pre-state. So success = quest present in active/ready after the call.
    s1 = _quest_state(c['after'], str(c['handle']))
    if s1 in ('active', 'in_progress', 'ready', 'complete'):
        return 'success'
    return 'inconclusive'

def verify_quest_turn_in(c):
    """Честный вердикт сдачи квеста.

    ГЛАВНЫЙ СИГНАЛ (найден 2026-08-24 вместе с со-диагностом): рост счётчика
    quests_done. В ОНЛАЙНЕ ведро `done` всегда пусто, потому что завершённый
    квест УДАЛЯЕТСЯ из questLog (quest_commands.ts:432-433), а истина живёт в
    online.questsDone (Set) — мост теперь отдаёт его размер (quests_done.cjs).

    Раньше проверялось только ведро done и смена состояния, поэтому КАЖДАЯ
    успешная сдача помечалась inconclusive: реально сдано 7 квестов (wolves,
    boars, bandits, murlocs, spiders, kitchens, loom), а метрика показывала 0.
    Агент учился, что сдавать квесты бесполезно.
    """
    d0 = c['before'].get('quests_done')
    d1 = c['after'].get('quests_done')
    if isinstance(d0, (int, float)) and isinstance(d1, (int, float)) and d1 > d0:
        return 'success'
    if not c['handle']:
        # без quest_id и без роста счётчика доказательств успеха нет, а
        # действие было ПОПЫТКОЙ -> провал попытки, не неопределённость
        return 'failure'
    qid = str(c['handle'])
    b_done = c['before'].get('quests', {}).get('done', [])
    a_done = c['after'].get('quests', {}).get('done', [])
    if qid in a_done and qid not in b_done:
        return 'success'
    s0 = _quest_state(c['before'], qid)
    s1 = _quest_state(c['after'], qid)
    if s0 in ('active', 'ready', 'complete') and s1 == 'done':
        return 'success'
    # Квест ИСЧЕЗ из лога, но счётчик не вырос -> сервер отклонил либо ресинк.
    # Это провал попытки: иначе агент бесконечно спамит сдачу без сигнала.
    if s0 is not None and s1 is None:
        return 'failure'
    # Fix2 (2026-08-23): the server REJECTS doomed turn-ins silently — no error
    # event reaches the client (probed live: quest stays ready, no events). A
    # rejected attempt left the world unchanged, which used to be
    # 'inconclusive' (reward 0) and made blind turn-in spam FREE (measured:
    # 350x turn_in_quest all inconclusive in one run). Unchanged evidence on an
    # ATTEMPTED action is a failure of that attempt.
    if s0 is not None and s1 is not None and s0 == s1:
        return 'failure'
    return 'inconclusive'

def verify_sell_junk(c):
    j0 = len(_junk_items(c['before'])); j1 = len(_junk_items(c['after']))
    c0 = _player_copper(c['before']); c1 = _player_copper(c['after'])
    if j1 < j0 and c1 > c0:
        return 'success'
    return 'inconclusive'

def verify_gather(c):
    h = c.get('handle') or {}
    node_id = h.get('nodeId'); mat_id = h.get('materialId')
    nb = _node_by_id(c['before'], node_id); na = _node_by_id(c['after'], node_id)
    consumed = nb and nb.get('harvestable') and not (na and na.get('harvestable'))
    mb = _item_count(c['before'], mat_id) if mat_id else _inv_total(c['before'])
    ma = _item_count(c['after'], mat_id) if mat_id else _inv_total(c['after'])
    if consumed and ma > mb:
        return 'success'
    if ma > mb:
        return 'success'
    # 2026-08-24: если МОСТ не нашёл ни узла, ни трупа (noTarget=True), это
    # честный ПРОВАЛ решения, а не неопределённость: агент выбрал скилл,
    # которому физически нечего делать. Измерено: 25 подряд gather в пустоту
    # на позиции без трупов -> все inconclusive -> reward~0 -> Q ничему не
    # училось и цикл мог длиться бесконечно. Отсутствие флага (старые записи)
    # сохраняет прежнее поведение.
    if h.get('noTarget') is True:
        return 'failure'
    return 'inconclusive'

def verify_craft(c):
    h = c.get('handle') or {}
    out_id = h.get('outputItemId')
    b = _item_count(c['before'], out_id) if out_id else _inv_total(c['before'])
    a = _item_count(c['after'], out_id) if out_id else _inv_total(c['after'])
    if a > b:
        return 'success'
    return 'inconclusive'

_POTION_RE = None  # compiled lazily below

def verify_heal(c):
    h0 = _player_hp(c['before']); h1 = _player_hp(c['after'])
    if h1 > h0 or h1 >= _player_hp_max(c['after']):
        return 'success'
    # hp did not rise: was a potion actually consumed? If not, this heal attempt
    # was a no-op (no supplies) and MUST be 'failure' — 'inconclusive' gave ~zero
    # negative signal, so the agent kept re-trying heal at crit HP instead of
    # retreating (observed death loop, run 14844).
    import re
    global _POTION_RE
    if _POTION_RE is None:
        _POTION_RE = re.compile(r'potion|draught|tonic|elixir|heal', re.IGNORECASE)
    def _potions(inv):
        return sum(1 for it in (inv or [])
                   if isinstance(it, dict) and _POTION_RE.search((it.get('name') or '')))
    p0 = _potions(c['before'].get('inventory'))
    p1 = _potions(c['after'].get('inventory'))
    if p1 < p0:
        return 'inconclusive'   # potion spent but hp did not rise (resisted?) — rare, don't punish
    return 'failure'

def verify_equip(c):
    h = c.get('handle') or {}
    slot = h.get('slot'); item_id = h.get('itemId')
    e0 = _equip_slot(c['before'], slot); e1 = _equip_slot(c['after'], slot)
    if slot and e0 != e1:
        return 'success'
    if slot and item_id and e1 == item_id:
        return 'success'
    return 'inconclusive'

def verify_buy(c):
    h = c.get('handle') or {}
    item_id = h.get('itemId')
    c0 = _player_copper(c['before']); c1 = _player_copper(c['after'])
    i0 = _item_count(c['before'], item_id) if item_id else _inv_total(c['before'])
    i1 = _item_count(c['after'], item_id) if item_id else _inv_total(c['after'])
    if i1 > i0 and c1 < c0:
        return 'success'
    return 'inconclusive'


VERIFIERS = {
    'farm': verify_farm, 'loot': verify_loot, 'accept_quest': verify_quest_accept,
    'turn_in_quest': verify_quest_turn_in, 'sell_junk': verify_sell_junk,
    'gather': verify_gather, 'craft': verify_craft, 'heal': verify_heal,
    'equip': verify_equip, 'buy': verify_buy,
}

def verify_skill(name, ctx):
    v = VERIFIERS.get(name)
    if v:
        return v(ctx)
    # Mage cast skills (cast_frostbolt / cast_fireball): SUCCESS on any honest
    # combat consequence — mob hp dropped, mob died, or xp rose. Without this
    # every cast returned 'inconclusive' (reward 0) and the Q-table could never
    # prefer a ranged nuke over melee farm.
    if name in ('cast_frostbolt', 'cast_fireball'):
        b, a = ctx['before'], ctx['after']
        if (a.get('player') or {}).get('xp', 0) > (b.get('player') or {}).get('xp', 0):
            return 'success'
        if _player_kills(a) > _player_kills(b):
            return 'success'
        before_mobs = {(e.get('id')): e for e in (b.get('nearby') or [])
                       if (e.get('kind') == 'mob' or e.get('type') == 'mob')}
        after_mobs = {(e.get('id')): e for e in (a.get('nearby') or [])
                      if (e.get('kind') == 'mob' or e.get('type') == 'mob')}
        for mid, me in before_mobs.items():
            if not me.get('dead') and (me.get('hp') or 0) > 0:
                ae = after_mobs.get(mid)
                if ae is None or ae.get('dead') or (ae.get('hp') or 0) < (me.get('hp') or 0):
                    return 'success'
        return 'inconclusive'
    return 'inconclusive'
