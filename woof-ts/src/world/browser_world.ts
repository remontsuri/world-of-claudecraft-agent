/**
 * browser_world.ts — мир игры В БРАУЗЕРЕ (задача C1, офлайн-режим Vite :5173).
 *
 * Зачем отдельный адаптер: офлайн-режим — это мир внутри страницы, без сервера и
 * без сокета, поэтому ни `sim_world` (in-process Sim), ни WS-клиент (A1) к нему
 * не подходят. Единственная честная связь — CDP (`src/bridge/cdp_client.ts`).
 *
 * Наследство замороженной Java-линии (`woof-agent/`, роль — источник архитектуры):
 * поведение перенесено из рабочего эталона `tools/ref/snapshot.cjs` (456 строк) и
 * `tools/ref/actions.cjs` (968 строк), включая найденные живьём грабли:
 *  - `qp.resolvedCounts[i]` — АВТОРИТЕТНОЕ `required` (с учётом ранга/талантов),
 *    а `qp.counts[i]` — ТЕКУЩИЙ прогресс. Подмена одного другим давала «0/0 ACTIVE»
 *    на готовых квестах и наоборот — агент ходил кругами;
 *  - `sim.questState(qid)` в офлайне авторитетен (проверено эталоном 2026-08-27):
 *    'available'|'active'|'done'|'unavailable' — поэтому questStateApi='full';
 *  - ЖИВЫЕ позиции NPC — авторитетный источник для сдачи: статические таблицы
 *    разъезжались с реальным миром. Пины из контента игры остаются запасным слоем;
 *  - `controller.face()` в офлайне — **no-op** (проверено эталоном): курс задаётся
 *    только `controller.move({turnLeft|turnRight|forward}, desiredFacing)`;
 *  - единый порог курса даёт автоколебание камеры (баг, замеченный владельцем
 *    2026-08-24 дважды) — лечится гистерезисом 0.35/0.10 рад и памятью состояния;
 *  - в бою при hp<50% надо УБЕГАТЬ от ближайшего врага, а не идти сквозь пачку
 *    (leash сбрасывает аггро; хождение сквозь пачку дало 30 смертей за прогон).
 *
 * Чего здесь НЕТ по сравнению с эталоном и почему:
 *  - захардкоженных таблиц квестов (`QUEST_OBJECTIVES`) — контент берётся импортом
 *    из дерева игры (`src/facts.ts` → `game/src/sim/data`), а не из страницы и не
 *    из кода: страница отдаёт `questDefs`/`npcDefs` ненадёжно, это факт эталона;
 *  - доспавна квестодателей через `sim.addEntity` — мир не подделываем: если NPC
 *    не виден, это находка зонда, а не повод нарисовать его;
 *  - HTTP-моста на :8791 — агент говорит с вкладкой напрямую, слушать нечего
 *    (долг J12 замороженной линии закрыт отсутствием сокета).
 *
 * Честность возможностей: страница НЕ обязана иметь все методы. `snapshotExpression`
 * возвращает карту `api` (`typeof` каждого кандидата), и действие, которому метода
 * не хватает, возвращает `UNSUPPORTED:<причина>`, а не «успех» и не выдуманный вызов.
 */
import { angleTo, normAngle } from '../../game/src/sim/types';
import { gameFacts, npcPins, questDef, questOrder, type GameFacts } from '../facts';
import { isQuestCompletable } from './quest_policy';
import { describeCapabilities, type WorldCapabilities } from './world';
import {
  VIEW_RADIUS,
  type Counters,
  type EntityView,
  type MapPin,
  type ObjectiveView,
  type QuestStateName,
  type QuestView,
  type WorldModel,
} from './types';
import type { AbilityView } from './sim_world';

/** Как мы говорим со страницей. В жизни — `CdpSession.evaluate`, в тесте — фейк
 *  (без портов и без серверов: долг J11 замороженной линии закрыт конструкцией). */
export type PageEvaluate = (expression: string) => Promise<unknown>;

/** Методы страницы, которые нам могут понадобиться. Присутствие проверяется
 *  живьём (`typeof`), а не по вере в документацию. */
export const PAGE_API_CANDIDATES = [
  'sim.targetEntity',
  'sim.startAutoAttack',
  'sim.stopAutoAttack',
  'sim.interact',
  'sim.lootCorpse',
  'sim.acceptQuest',
  'sim.turnInQuest',
  'sim.abandonQuest',
  'sim.sellItem',
  'sim.useItem',
  'sim.entitiesNear',
  'sim.questState',
  'sim.useAbility',
  'sim.castAbility',
  'sim.castSpell',
  'sim.respawn',
  'sim.releaseSpirit',
  'sim.addEntity',
  'controller.move',
  'controller.stop',
  'controller.face',
] as const;

/** Квесты, которые мы НЕ берём, пока навык не реализован здесь (иначе агент
 *  наберёт то, что не может сдать — ровно долг A2). Причина печатается до прогона. */
export const BROWSER_UNSUPPORTED_OBJECTIVES: Record<string, string> = {
  gather: 'навык gather не перенесён в браузерную линию (C1.3): узлы сбора и подход к ним',
  escort: 'сопровождение не перенесено: нет ведения NPC по маршруту',
  craft: 'навык craft не перенесён (нужен `sim.recipeList` + станок)',
};

/** Цель квеста, которую мы честно умеем делать в браузере уже сейчас. */
export function browserCompletable(qid: string): { ok: boolean; reason: string | null } {
  if (!isQuestCompletable(qid)) return { ok: false, reason: 'квест непроходим по политике (quest_policy)' };
  let def;
  try {
    def = questDef(qid);
  } catch (e) {
    return { ok: false, reason: (e as Error).message };
  }
  for (const o of def.objectives) {
    const why = BROWSER_UNSUPPORTED_OBJECTIVES[o.type];
    if (why) return { ok: false, reason: `${o.type}: ${why}` };
  }
  return { ok: true, reason: null };
}

// ---------------------------------------------------------------------------
// Выражения для страницы. Всё — чистый JS строкой: внутри страницы нет ни
// require, ни import наших модулей (баг эталона 2026-08-25: «QUEST_OBJECTIVES is
// not defined» ронял весь снимок). Данные передаём инлайном через JSON.
// ---------------------------------------------------------------------------

/** Снимок мира: только чтение. Никаких applyAction/записи в window.__game. */
export function snapshotExpression(questIds: readonly string[], viewRadius = VIEW_RADIUS): string {
  const ids = JSON.stringify([...questIds]);
  const api = JSON.stringify([...PAGE_API_CANDIDATES]);
  return `(async () => {
  const g = window.__game;
  if (!g || !g.sim) return { ok: false, reason: 'no_game', gameKeys: g ? Object.keys(g) : [] };
  const sim = g.sim, p = sim.player;
  if (!p || !p.pos) return { ok: false, reason: 'no_player', simKeys: Object.keys(sim).slice(0, 60) };
  const QUEST_IDS = ${ids}, R = ${viewRadius}, CANDIDATES = ${api};
  const typeofAt = (path) => {
    try {
      const parts = path.split('.');
      let cur = parts[0] === 'sim' ? sim : (parts[0] === 'controller' ? g.controller : g[parts[0]]);
      for (let i = 1; i < parts.length; i++) { if (cur == null) return 'missing'; cur = cur[parts[i]]; }
      return typeof cur;
    } catch (_) { return 'error'; }
  };
  const api = {};
  for (const c of CANDIDATES) api[c] = typeofAt(c);
  const qs = {};
  for (const qid of QUEST_IDS) {
    try { qs[qid] = (typeof sim.questState === 'function') ? String(sim.questState(qid)) : 'unknown'; }
    catch (_) { qs[qid] = 'error'; }
  }
  const qlog = [];
  const log = sim.questLog || (g.world && g.world.questLog) || null;
  if (log && typeof log.forEach === 'function') {
    log.forEach((qp, qid) => qlog.push({
      id: String(qid), state: String(qp.state || 'active'),
      counts: Array.isArray(qp.counts) ? qp.counts.slice() : [],
      resolvedCounts: Array.isArray(qp.resolvedCounts) ? qp.resolvedCounts.slice() : [],
    }));
  }
  const ents = [];
  const kindCounts = {};
  for (const e of sim.entities.values()) {
    if (!e || !e.pos) continue;
    kindCounts[e.kind || 'none'] = (kindCounts[e.kind || 'none'] || 0) + 1;
    const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, dist = Math.hypot(dx, dz);
    if (dist > R) continue;
    ents.push({
      id: e.id, kind: e.kind || null, name: e.name || null,
      templateId: e.templateId || e.mobId || null,
      level: (typeof e.level === 'number' ? e.level : null),
      hp: (typeof e.hp === 'number' ? e.hp : null),
      maxHp: (typeof e.maxHp === 'number' ? e.maxHp : null),
      hostile: !!e.hostile, dead: !!e.dead, lootable: !!e.lootable, looted: !!e.looted,
      inCombat: !!e.inCombat, aggroTargetId: (e.aggroTargetId != null ? e.aggroTargetId : null),
      x: e.pos.x, z: e.pos.z, dist,
      questIds: Array.isArray(e.questIds) ? e.questIds.map(String) : (e.questId ? [String(e.questId)] : []),
      vendorItems: Array.isArray(e.vendorItems) ? e.vendorItems.length : 0,
    });
  }
  const known = (typeof sim.known !== 'undefined' && sim.known) ? sim.known : [];
  const abilities = [];
  for (let i = 0; i < known.length; i++) {
    const k = known[i];
    if (!k || !k.def || k.def.passive) continue;
    const cd = (p.cooldowns && typeof p.cooldowns.get === 'function' && p.cooldowns.get(k.def.id)) || 0;
    abilities.push({
      slot: i, id: String(k.def.id), name: String(k.def.name || k.def.id),
      ready: cd <= 0, cooldownLeft: cd,
      cooldown: (k.cooldown != null ? k.cooldown : (k.def.cooldown || 0)),
      cost: (k.cost != null ? k.cost : (k.def.cost || 0)),
      range: (k.def.range || 0),
    });
  }
  const inv = (p.inventory || sim.inventory || []);
  const inventory = inv.map((s) => ({
    id: (s && (s.itemId || s.id)) ? String(s.itemId || s.id) : null,
    count: (s && s.count != null) ? s.count : 1,
  }));
  const npcPositions = {};
  for (const e of sim.entities.values()) {
    if (e && e.kind === 'npc' && e.templateId && e.pos) npcPositions[String(e.templateId)] = { x: e.pos.x, z: e.pos.z };
  }
  const w = g.world;
  const primary = (w && w.players && w.primaryId != null && typeof w.players.get === 'function')
    ? w.players.get(w.primaryId) : null;
  return {
    ok: true, reason: null, api, kindCounts,
    player: {
      hp: p.hp, maxHp: p.maxHp, level: p.level,
      xp: (typeof p.xp === 'number' ? p.xp : null),
      copper: (typeof p.copper === 'number' ? p.copper : (typeof p.money === 'number' ? p.money : null)),
      facing: p.facing, dead: !!p.dead, inCombat: !!p.inCombat,
      autoAttack: !!p.autoAttack, resting: !!p.resting,
      resource: (typeof p.resource === 'number' ? p.resource : 0),
      maxResource: (typeof p.maxResource === 'number' ? p.maxResource : 0),
      resourceType: String(p.resourceType || 'mana'),
      playerClass: String(p.class || p.playerClass || ''),
      targetId: (p.targetId != null ? p.targetId : null),
      x: p.pos.x, z: p.pos.z,
    },
    playerId: (sim.playerId != null ? sim.playerId : (p.id != null ? p.id : null)),
    entities: ents, questStates: qs, questLog: qlog, abilities, inventory, npcPositions,
    bags: Array.isArray(sim.bags) ? sim.bags.length : 0,
    bagCapacity: (typeof sim.bagCapacity === 'number' ? sim.bagCapacity : 16),
    primaryKeys: primary ? Object.keys(primary) : [],
    primaryStats: (primary && primary.stats) ? JSON.parse(JSON.stringify(primary.stats)) : null,
    controllerKeys: g.controller ? Object.keys(g.controller) : [],
    tick: (typeof sim.tick === 'number' ? sim.tick : (typeof sim.worldTick === 'number' ? sim.worldTick : null)),
    time: (typeof sim.time === 'number' ? sim.time : null),
  };
})()`;
}

/** Гистерезис курса: вход 0.35 рад, выход 0.10 рад, идти вперёд при |off|<=1.20.
 *  Состояние живёт в `window.__navTurning` (память между тиками, как в эталоне). */
export const TURN_HELPER = `
  const __TURN_START = 0.35, __TURN_STOP = 0.10, __TURN_ONLY = 1.20;
  const __navDecide = (off) => {
    const mag = Math.abs(off);
    const wasTurning = !!window.__navTurning;
    const threshold = wasTurning ? __TURN_STOP : __TURN_START;
    if (mag <= threshold) { window.__navTurning = false; return { forward: true }; }
    window.__navTurning = true;
    const left = off > 0;
    const fwd = mag <= __TURN_ONLY;
    return left ? { turnLeft: true, forward: fwd } : { turnRight: true, forward: fwd };
  };
`;

/** Один тик навигации к точке. Возвращает факт: где мы, какой ввод применён,
 *  arrived/fleeing. Мир при этом НЕ перезагружается и ввод человека не трогается. */
export function navStepExpression(tx: number, tz: number, arriveYards = 5): string {
  return `(() => {
  const g = window.__game;
  if (!g || !g.sim || !g.sim.player || !g.sim.player.pos) return { ok: false, reason: 'no_game' };
  const sim = g.sim, p = sim.player;
  const dx = ${tx} - p.pos.x, dz = ${tz} - p.pos.z, d = Math.hypot(dx, dz);
  if (d < ${arriveYards}) {
    window.__navTurning = false;
    try { if (typeof g.controller.stop === 'function') g.controller.stop(); } catch (_) {}
    return { ok: true, arrived: true, d, x: p.pos.x, z: p.pos.z, input: { stop: true } };
  }
  // FLEE: в бою при hp<50% бежим ОТ ближайшего врага (leash сбрасывает аггро).
  if (p.inCombat && (p.hp / Math.max(p.maxHp, 1)) < 0.5) {
    let nearest = null, nd = Infinity;
    for (const e of sim.entities.values()) {
      if (!e || !e.pos) continue;
      if (e.kind !== 'mob' || e.dead || (e.hp != null && e.hp <= 0) || e.hostile === false) continue;
      const ed = Math.hypot(e.pos.x - p.pos.x, e.pos.z - p.pos.z);
      if (ed < nd) { nd = ed; nearest = e; }
    }
    if (nearest && nd < 25) {
      const flee = Math.atan2(p.pos.x - nearest.pos.x, p.pos.z - nearest.pos.z);
      try { g.controller.move({ forward: true }, flee); } catch (_) {}
      return { ok: true, arrived: false, fleeing: true, d, x: p.pos.x, z: p.pos.z, input: { forward: true, facing: flee } };
    }
  }
  const desired = Math.atan2(dx, dz);
  let off = desired - p.facing;
  off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
  ${TURN_HELPER}
  const input = __navDecide(off);
  try { g.controller.move(input, desired); } catch (e) { return { ok: false, reason: 'move_failed: ' + (e && e.message) }; }
  return { ok: true, arrived: false, d, off, x: p.pos.x, z: p.pos.z, input, desired };
})()`;
}

/** Действие в странице: вызываем ТОЛЬКО метод, присутствие которого подтверждено
 *  в `api` (проверяет Node-сторона до отправки). Ответ — факт, а не намерение. */
export function actionExpression(
  kind: 'attack' | 'loot' | 'accept' | 'turnIn' | 'interact' | 'respawn' | 'cast' | 'stopAttack',
  args: { id?: number | null; questId?: string | null; abilityId?: string | null; playerId?: number | null } = {},
): string {
  const a = JSON.stringify(args);
  const body: Record<typeof kind, string> = {
    attack: `
      if (A.id == null) return { ok: false, reason: 'no_id' };
      sim.targetEntity(A.id);
      if (typeof sim.startAutoAttack === 'function') sim.startAutoAttack();
      const e = sim.entities.get ? sim.entities.get(A.id) : null;
      return { ok: true, targeted: A.id, autoAttack: !!p.autoAttack, targetHp: e ? e.hp : null };`,
    stopAttack: `
      if (typeof sim.stopAutoAttack === 'function') sim.stopAutoAttack();
      return { ok: true, autoAttack: !!p.autoAttack };`,
    loot: `
      if (A.id == null) return { ok: false, reason: 'no_id' };
      const r = sim.lootCorpse(A.id, A.playerId != null ? A.playerId : p.id);
      return { ok: true, result: (r && typeof r === 'object') ? JSON.parse(JSON.stringify(r)) : (r === undefined ? null : r) };`,
    accept: `
      if (!A.questId) return { ok: false, reason: 'no_quest' };
      const r = sim.acceptQuest(String(A.questId), null, A.playerId != null ? A.playerId : p.id);
      let state = 'unknown';
      try { state = String(sim.questState(String(A.questId))); } catch (_) {}
      return { ok: true, state, result: (r === undefined ? null : (typeof r === 'object' ? JSON.parse(JSON.stringify(r)) : r)) };`,
    turnIn: `
      if (!A.questId) return { ok: false, reason: 'no_quest' };
      const r = sim.turnInQuest(String(A.questId));
      let state = 'unknown';
      try { state = String(sim.questState(String(A.questId))); } catch (_) {}
      return { ok: true, state, result: (r === undefined ? null : (typeof r === 'object' ? JSON.parse(JSON.stringify(r)) : r)) };`,
    interact: `
      sim.interact();
      return { ok: true };`,
    respawn: `
      if (typeof sim.respawn === 'function') { sim.respawn(); return { ok: true, via: 'sim.respawn' }; }
      if (typeof sim.releaseSpirit === 'function') { sim.releaseSpirit(); return { ok: true, via: 'sim.releaseSpirit' }; }
      return { ok: false, reason: 'no_respawn_api' };`,
    cast: `
      if (!A.abilityId) return { ok: false, reason: 'no_ability' };
      if (typeof sim.useAbility === 'function') { sim.useAbility(String(A.abilityId)); return { ok: true, via: 'sim.useAbility' }; }
      if (typeof sim.castAbility === 'function') { sim.castAbility(String(A.abilityId)); return { ok: true, via: 'sim.castAbility' }; }
      if (typeof sim.castSpell === 'function') { sim.castSpell(String(A.abilityId)); return { ok: true, via: 'sim.castSpell' }; }
      return { ok: false, reason: 'no_cast_api' };`,
  };
  return `(() => {
  const A = ${a};
  const g = window.__game;
  if (!g || !g.sim || !g.sim.player) return { ok: false, reason: 'no_game' };
  const sim = g.sim, p = sim.player;
  try {${body[kind]}
  } catch (e) { return { ok: false, reason: String((e && e.message) || e) }; }
})()`;
}

// ---------------------------------------------------------------------------
// Сырой снимок страницы и его разбор в WorldModel (чистая функция — тестируется).
// ---------------------------------------------------------------------------

export interface RawEntity {
  id: number;
  kind: string | null;
  name: string | null;
  templateId: string | null;
  level: number | null;
  hp: number | null;
  maxHp: number | null;
  hostile: boolean;
  dead: boolean;
  lootable: boolean;
  looted: boolean;
  inCombat: boolean;
  aggroTargetId: number | null;
  x: number;
  z: number;
  dist: number;
  questIds: string[];
  vendorItems: number;
}

export interface RawSnapshot {
  ok: boolean;
  reason: string | null;
  gameKeys?: string[];
  simKeys?: string[];
  api: Record<string, string>;
  kindCounts: Record<string, number>;
  player: {
    hp: number;
    maxHp: number;
    level: number;
    xp: number | null;
    copper: number | null;
    facing: number;
    dead: boolean;
    inCombat: boolean;
    autoAttack: boolean;
    resting: boolean;
    resource: number;
    maxResource: number;
    resourceType: string;
    playerClass: string;
    targetId: number | null;
    x: number;
    z: number;
  };
  playerId: number | null;
  entities: RawEntity[];
  questStates: Record<string, string>;
  questLog: { id: string; state: string; counts: number[]; resolvedCounts: number[] }[];
  abilities: { slot: number; id: string; name: string; ready: boolean; cooldownLeft: number; cooldown: number; cost: number; range: number }[];
  inventory: { id: string | null; count: number }[];
  npcPositions: Record<string, { x: number; z: number }>;
  bags: number;
  bagCapacity: number;
  primaryKeys: string[];
  primaryStats: Record<string, unknown> | null;
  controllerKeys: string[];
  tick: number | null;
  time: number | null;
}

/** Разбор ответа страницы. Не-объект и `ok:false` — ПРОВАЛ с причиной: молча
 *  вернуть пустой мир значило бы «агент наблюдает ничего», как в аудите Java-линии. */
export function parseSnapshot(value: unknown): RawSnapshot {
  if (typeof value !== 'object' || value === null) {
    throw new Error(`ПРОВАЛ: страница вернула не объект (${typeof value}) — снимок не прочитан`);
  }
  const raw = value as Partial<RawSnapshot>;
  if (raw.ok !== true) {
    const reason = raw.reason ?? 'неизвестно';
    const hint =
      reason === 'no_game'
        ? 'Вкладка не в мире: нужно http://localhost:5173 → «Play Offline» → войти в мир персонажем.'
        : reason === 'no_player'
          ? 'Вкладка в игре, но мир ещё не создан (загрузка/меню): войди в мир и повтори зонд.'
          : 'страница отказала';
    throw new Error(`ПРОВАЛ: снимок страницы не собран (${reason}). ${hint}`);
  }
  if (!raw.player || !Array.isArray(raw.entities) || !raw.api) {
    throw new Error('ПРОВАЛ: в снимке нет player/entities/api — поверхность страницы не та, что ждём');
  }
  return raw as RawSnapshot;
}

export interface MapOptions {
  facts: GameFacts;
  questIds: readonly string[];
  /** Номер решения агента (мир реального времени: своего «тика мира» у нас нет). */
  step: number;
  /** Счётчики, которые ведёт Node-сторона (см. CountersProvenance). */
  counters: Counters;
  playerId: number | null;
}

/** Чистый разбор снимка в `WorldModel`. Вынесена из класса, чтобы тестировать
 *  маппинг без CDP и без браузера (полигон, долг J11 — закрыт конструкцией). */
export function mapSnapshot(raw: RawSnapshot, opts: MapOptions): WorldModel {
  const { facts, questIds, step, counters, playerId } = opts;
  const p = raw.player;
  const states = raw.questStates;
  const logById = new Map(raw.questLog.map((q) => [q.id, q]));

  const kindOf = (k: string | null): 'mob' | 'npc' | 'object' | 'player' =>
    k === 'mob' || k === 'npc' || k === 'player' ? k : 'object';

  const entities: EntityView[] = raw.entities.map((e) => {
    const bearing = normAngle(angleTo({ x: p.x, y: 0, z: p.z }, { x: e.x, y: 0, z: e.z }) - p.facing);
    const qids = e.questIds;
    const available = qids.filter((q) => states[q] === 'available');
    const completable = available.filter((q) => browserCompletable(q).ok);
    return {
      id: e.id,
      kind: kindOf(e.kind),
      templateId: e.templateId ?? '',
      name: e.name ?? e.templateId ?? `#${e.id}`,
      level: e.level ?? p.level,
      hp: e.hp ?? 0,
      maxHp: e.maxHp ?? Math.max(1, e.hp ?? 0),
      hostile: !!e.hostile,
      dead: !!e.dead,
      lootable: !!e.lootable && !e.looted,
      questIds: qids,
      availableQuests: available,
      completableQuests: completable,
      aggroOnMe: playerId != null && e.aggroTargetId === playerId,
      x: e.x,
      z: e.z,
      dist: e.dist,
      bearing,
    };
  });

  const npcs = entities.filter((e) => e.kind === 'npc').sort((a, b) => a.dist - b.dist);
  const mobs = entities.filter((e) => e.kind === 'mob').sort((a, b) => a.dist - b.dist);
  const objects = entities.filter((e) => e.kind === 'object' || e.kind === 'player').sort((a, b) => a.dist - b.dist);
  const corpses = entities.filter((e) => e.lootable).sort((a, b) => a.dist - b.dist);

  // Квесты: active/ready/done — всегда (это наше состояние), available — только
  // если его отдаёт ВИДИМЫЙ NPC (иначе шум, как в sim_world).
  const quests: QuestView[] = [];
  for (const qid of questIds) {
    const st = states[qid];
    if (!st) continue;
    const state: QuestStateName =
      st === 'available' || st === 'active' || st === 'ready' || st === 'done' ? st : 'other';
    const offeredByVisibleNpc = npcs.some((n) => n.questIds.includes(qid));
    if (state === 'available' && !offeredByVisibleNpc) continue;
    let def;
    try {
      def = questDef(qid);
    } catch {
      continue; // квеста нет в дереве игры — не выдумываем определение
    }
    const log = logById.get(qid);
    const objectives: ObjectiveView[] = def.objectives.map((o, i) => {
      // required — из resolvedCounts (авторитет, ранг/таланты учтены), НЕ из counts.
      const required = log?.resolvedCounts?.[i] ?? o.count;
      const have = log?.counts?.[i] ?? 0;
      return {
        type: o.type,
        targetMobId: o.targetMobId,
        targetNpcId: o.targetNpcId,
        itemId: o.itemId,
        targetObjectItemId: o.targetObjectItemId,
        required,
        have,
        label: o.label,
      };
    });
    const required = objectives.reduce((s, o) => s + o.required, 0);
    const have = objectives.reduce((s, o) => s + Math.min(o.have, o.required), 0);
    quests.push({
      id: qid,
      name: def.name,
      state,
      objectives,
      progress: required > 0 ? have / required : 0,
      required,
      giverNpcId: def.giverNpcId,
      turnInNpcId: def.turnInNpcId ?? def.giverNpcId,
    });
  }

  // Слой карты: статические пины из контента игры, но ЖИВАЯ позиция NPC важнее
  // (урок эталона: статические таблицы разъезжались с реальным миром).
  const mapPins: MapPin[] = [];
  for (const pin of npcPins()) {
    const live = raw.npcPositions[pin.templateId];
    const x = live?.x ?? pin.x;
    const z = live?.z ?? pin.z;
    const dist = Math.hypot(x - p.x, z - p.z);
    for (const qid of pin.questIds) {
      const st = states[qid];
      const isTurnIn = quests.some((q) => q.id === qid && (q.state === 'ready' || q.state === 'active') && q.turnInNpcId === pin.templateId);
      const isGiver = st === 'available';
      if (!isGiver && !isTurnIn) continue;
      mapPins.push({ templateId: pin.templateId, name: pin.name, x, z, kind: isTurnIn ? 'turnin' : 'giver', questId: qid, dist });
    }
  }
  mapPins.sort((a, b) => a.dist - b.dist);

  const targetId = p.targetId;
  const target = targetId != null ? (entities.find((e) => e.id === targetId) ?? null) : null;

  return {
    step,
    time: raw.time ?? Date.now() / 1000,
    player: {
      hp: p.hp,
      maxHp: p.maxHp,
      resource: p.resource,
      maxResource: p.maxResource,
      resourceType: p.resourceType,
      level: p.level,
      xp: p.xp ?? 0,
      x: p.x,
      z: p.z,
      facing: p.facing,
      dead: p.dead,
      inCombat: p.inCombat,
      autoAttack: p.autoAttack,
      resting: p.resting,
      playerClass: p.playerClass,
      targetId,
    },
    target,
    nearby: mobs,
    npcs,
    objects,
    corpses,
    mapPins,
    quests,
    counters,
    copper: p.copper ?? 0,
  };
}

/** Откуда берутся счётчики. Всё, что не авторитетно, объявлено здесь и печатается
 *  до прогона: выдуманное число в evidence — подделка доказательства. */
export interface CountersProvenance {
  kills: string;
  deaths: string;
  questsCompleted: string;
  damage: string;
  copper: string;
}

export const COUNTERS_PROVENANCE: CountersProvenance = {
  kills: 'НАБЛЮДАЕМОЕ: переход враждебного моба alive→dead/исчезновение, пока мы в бою или с целью; сверяется с прогрессом kill-целей квеста',
  deaths: 'НАБЛЮДАЕМОЕ: переход player.dead false→true',
  questsCompleted: 'АВТОРИТЕТНОЕ: число квестов с sim.questState()===done',
  damage: 'НЕТ: страница не отдаёт накопленный урон → 0 и не используется как сигнал',
  copper: 'со страницы (player.copper/money), если поля нет — 0',
};

export interface BrowserWorldOptions {
  evaluate: PageEvaluate;
  facts?: GameFacts;
  questIds?: readonly string[];
  viewRadius?: number;
  /** Такт навигации, мс (эталон: ~220 мс). */
  navTickMs?: number;
  log?: (line: string) => void;
}

/**
 * Мир в браузере. АСИНХРОННЫЙ: CDP — запрос/ответ, и синхронный шов `World`
 * здесь не подделывается (иначе был бы молчаливый адаптер). Слой решений
 * (`GoalFSM.syncFrom`, `ArbitrationLayer.decide`) чист по `WorldModel`, поэтому
 * переиспользуется без изменений в `src/core/browser_agent.ts`.
 */
export class BrowserWorld {
  readonly facts: GameFacts;
  readonly questIds: readonly string[];
  readonly viewRadius: number;
  readonly navTickMs: number;
  readonly capabilities: WorldCapabilities;
  /** Какие методы страницы реально есть (заполняется после первого снимка). */
  pageApi: Record<string, string> = {};
  /** Виды сущностей, которых нет в нашей модели (не молчим — печатаем). */
  unknownKinds: Record<string, number> = {};
  ended: string | null = null;
  counters: Counters = {
    kills: 0,
    deaths: 0,
    questsCompleted: 0,
    questProgress: 0,
    xpGained: 0,
    levelUps: 0,
    damageDealt: 0,
    damageTaken: 0,
    lootCopper: 0,
  };

  private readonly evaluate: PageEvaluate;
  private readonly log: (line: string) => void;
  private step = 0;
  private lastRaw: RawSnapshot | null = null;
  private lastModel: WorldModel | null = null;
  private lastLatencyMs = 0;
  private prevDead = false;
  private prevLevel = 0;
  private prevXp = 0;
  private prevAliveHostiles = new Map<number, { templateId: string | null; hp: number | null }>();
  private prevTargetId: number | null = null;
  private prevQuestObjectiveKills = 0;

  constructor(opts: BrowserWorldOptions) {
    this.evaluate = opts.evaluate;
    this.facts = opts.facts ?? gameFacts();
    this.questIds = opts.questIds ?? questOrder;
    this.viewRadius = opts.viewRadius ?? VIEW_RADIUS;
    this.navTickMs = opts.navTickMs ?? 220;
    this.log = opts.log ?? (() => undefined);
    this.capabilities = {
      transport: 'cdp',
      absoluteCoords: true,
      questStateApi: 'full',
      itemCountApi: true,
      contentData: true,
      deterministic: false,
      frameSkip: 0,
      realtime: true,
      otherPlayers: false,
      targetSelection: 'free',
      abandonQuest: false,
      vendor: true,
      partyLootRolls: false,
      commandVocabulary: 'page-api',
      entityIdentity: 'stable',
      entityTemplates: true,
      entityAbsoluteHp: true,
      damageCounters: false,
      questObjectiveCounts: true,
      latencyMs: 0,
    };
  }

  get currentStep(): number {
    return this.step;
  }

  get lastObservation(): WorldModel | null {
    return this.lastModel;
  }

  get lastSnapshot(): RawSnapshot | null {
    return this.lastRaw;
  }

  /** Объявление возможностей ДО прогона (правило проекта). */
  declare(): string[] {
    const missing = PAGE_API_CANDIDATES.filter((c) => this.pageApi[c] !== undefined && this.pageApi[c] !== 'function');
    return [
      ...describeCapabilities(this.capabilities),
      `среда=офлайн-dev (привилегированная: devCommands включены в dev-сервере) — замеры НЕ объявляются применимыми к честной игре`,
      `api страницы: подтверждено ${Object.values(this.pageApi).filter((v) => v === 'function').length}/${PAGE_API_CANDIDATES.length}` +
        (missing.length ? `, отсутствуют: ${missing.join(', ')}` : ''),
      `счётчики: ${COUNTERS_PROVENANCE.kills}; ${COUNTERS_PROVENANCE.deaths}; ${COUNTERS_PROVENANCE.questsCompleted}; урон — ${COUNTERS_PROVENANCE.damage}`,
      `не берём квесты: ${Object.entries(BROWSER_UNSUPPORTED_OBJECTIVES)
        .map(([k, v]) => `${k} (${v})`)
        .join('; ')}`,
      `задержка CDP ≈ ${this.lastLatencyMs} мс`,
    ];
  }

  /** Честная проверка здоровья: доказываем, что вкладка ЖИВАЯ и в мире. */
  async health(): Promise<{ ok: boolean; hp: number; level: number; x: number; z: number; api: Record<string, string> }> {
    const raw = await this.readSnapshot();
    return { ok: true, hp: raw.player.hp, level: raw.player.level, x: raw.player.x, z: raw.player.z, api: raw.api };
  }

  private async readSnapshot(): Promise<RawSnapshot> {
    const started = Date.now();
    const value = await this.evaluate(snapshotExpression(this.questIds, this.viewRadius));
    this.lastLatencyMs = Date.now() - started;
    const raw = parseSnapshot(value);
    this.pageApi = raw.api;
    this.unknownKinds = Object.fromEntries(
      Object.entries(raw.kindCounts).filter(([k]) => k !== 'mob' && k !== 'npc' && k !== 'object' && k !== 'player'),
    );
    this.lastRaw = raw;
    return raw;
  }

  /** Наблюдение + пересчёт НАБЛЮДАЕМЫХ счётчиков (см. COUNTERS_PROVENANCE). */
  async observe(): Promise<WorldModel> {
    const raw = await this.readSnapshot();
    this.step += 1;
    this.updateCounters(raw);
    const model = mapSnapshot(raw, {
      facts: this.facts,
      questIds: this.questIds,
      step: this.step,
      counters: { ...this.counters },
      playerId: raw.playerId,
    });
    this.lastModel = model;
    return model;
  }

  private updateCounters(raw: RawSnapshot): void {
    // смерти: переход dead false→true
    if (raw.player.dead && !this.prevDead) this.counters.deaths += 1;
    this.prevDead = raw.player.dead;
    // уровень/опыт
    if (this.prevLevel === 0) this.prevLevel = raw.player.level;
    if (raw.player.level > this.prevLevel) {
      this.counters.levelUps += raw.player.level - this.prevLevel;
      this.prevLevel = raw.player.level;
    }
    if (raw.player.xp != null) {
      if (this.prevXp === 0) this.prevXp = raw.player.xp;
      if (raw.player.xp > this.prevXp) this.counters.xpGained += raw.player.xp - this.prevXp;
      this.prevXp = raw.player.xp;
    }
    // квесты: АВТОРИТЕТНО по questState
    const done = Object.values(raw.questStates).filter((s) => s === 'done').length;
    this.counters.questsCompleted = done;
    // прогресс квеста: сумма долей по целям из журнала
    let progress = 0;
    for (const q of raw.questLog) {
      const req = q.resolvedCounts.reduce((s, n) => s + n, 0);
      const have = q.counts.reduce((s, n, i) => s + Math.min(n, q.resolvedCounts[i] ?? n), 0);
      progress += req > 0 ? have / req : 0;
    }
    this.counters.questProgress = progress;
    // убийства: наблюдаемый переход враждебного моба alive→dead/исчез, пока мы в бою
    const nowAlive = new Map<number, { templateId: string | null; hp: number | null }>();
    for (const e of raw.entities) {
      if (e.kind !== 'mob' || !e.hostile) continue;
      if (!e.dead && (e.hp == null || e.hp > 0)) nowAlive.set(e.id, { templateId: e.templateId, hp: e.hp });
    }
    if (this.prevAliveHostiles.size > 0) {
      // Цель умирает и страница сбрасывает targetId в тот же кадр, поэтому «в бою»
      // смотрим и по текущему кадру, и по прошлому: иначе убийства не считаются вовсе.
      const inFight = raw.player.inCombat || raw.player.targetId != null || this.prevTargetId != null;
      for (const [id] of this.prevAliveHostiles) {
        if (!nowAlive.has(id) && inFight) this.counters.kills += 1;
      }
    }
    this.prevTargetId = raw.player.targetId;
    this.prevAliveHostiles = nowAlive;
    // сверка: прогресс kill-целей квеста — второй, авторитетный источник
    let objectiveKills = 0;
    for (const q of raw.questLog) {
      let def;
      try {
        def = questDef(q.id);
      } catch {
        continue;
      }
      def.objectives.forEach((o, i) => {
        if (o.type === 'kill') objectiveKills += q.counts[i] ?? 0;
      });
    }
    if (objectiveKills > this.prevQuestObjectiveKills) {
      const gained = objectiveKills - this.prevQuestObjectiveKills;
      // если наблюдаемые убийства отстают от журнала квеста — доверяем журналу
      if (this.counters.kills < objectiveKills) this.counters.kills = objectiveKills;
      this.prevQuestObjectiveKills = objectiveKills;
      if (gained > 0) this.log(`[мир] kill-цели квеста +${gained} (всего ${objectiveKills})`);
    }
    this.prevQuestObjectiveKills = Math.max(this.prevQuestObjectiveKills, objectiveKills);
  }

  abilities(): AbilityView[] {
    const raw = this.lastRaw;
    if (!raw) return [];
    return raw.abilities.map((a) => ({
      slot: a.slot,
      id: a.id,
      ready: a.ready,
      cooldownFrac: a.cooldown > 0 ? Math.min(1, a.cooldownLeft / a.cooldown) : 0,
    }));
  }

  /** Число предметов в сумках (itemCountApi=true: страница отдаёт инвентарь). */
  countItem(itemId: string): number {
    const raw = this.lastRaw;
    if (!raw) throw new Error('ПРОВАЛ: countItem до первого снимка — сначала observe()');
    return raw.inventory.filter((s) => s.id === itemId).reduce((sum, s) => sum + s.count, 0);
  }

  /** Состояние квеста глазами игры (questStateApi='full'). */
  questState(questId: string): string {
    const raw = this.lastRaw;
    if (!raw) throw new Error('ПРОВАЛ: questState до первого снимка — сначала observe()');
    const st = raw.questStates[questId];
    if (!st) throw new Error(`ПРОВАЛ: страница не вернула состояние квеста "${questId}"`);
    return st;
  }

  /** Есть ли метод страницы. Без этого любое действие — выдумка. */
  has(method: string): boolean {
    return this.pageApi[method] === 'function';
  }

  private requireApi(method: string, skill: string): string | null {
    if (this.pageApi[method] === 'function') return null;
    const seen = this.pageApi[method] ?? 'не проверялось (нет снимка)';
    return `UNSUPPORTED:${skill}: страница не даёт ${method} (typeof=${seen}) — действие не выполнено, а не «выполнено молча»`;
  }

  /** Одно действие. Возвращает токен результата в той же конвенции, что и
   *  исполнитель стенда: 'OK...', 'NO_...', 'UNSUPPORTED:...', 'ERROR:...'. */
  async act(skill: string, w: WorldModel): Promise<string> {
    const interact = this.facts.interactRange;
    switch (skill) {
      case 'farm': {
        const missing = this.requireApi('sim.targetEntity', skill);
        if (missing) return missing;
        const target = pickFarmTarget(w, this.facts.meleeRange);
        if (!target) return 'NO_TARGET: враждебного моба в радиусе наблюдения нет';
        const res = (await this.runAction('attack', { id: target.id })) as { ok: boolean; reason?: string; targetHp?: number | null };
        if (!res?.ok) return `ERROR:farm:${res?.reason ?? 'страница отказала'}`;
        // Цель взята ПОСЛЕ наблюдения, а страница сбрасывает targetId в кадр смерти:
        // запоминаем её здесь, иначе убийство некому приписать (см. updateCounters).
        this.prevTargetId = target.id;
        return `OK farm id=${target.id} ${target.templateId} hp=${res.targetHp ?? '?'} dist=${target.dist.toFixed(1)}`;
      }
      case 'loot': {
        const missing = this.requireApi('sim.lootCorpse', skill);
        if (missing) return missing;
        const corpse = w.corpses.filter((c) => c.dist <= Math.max(interact, 12)).sort((a, b) => a.dist - b.dist)[0];
        if (!corpse) return 'NO_LOOT: трупа в радиусе нет';
        const res = (await this.runAction('loot', { id: corpse.id, playerId: this.lastRaw?.playerId ?? null })) as { ok: boolean; reason?: string };
        if (!res?.ok) return `ERROR:loot:${res?.reason ?? 'страница отказала'}`;
        return `OK loot id=${corpse.id} ${corpse.templateId}`;
      }
      case 'accept_quest': {
        const missing = this.requireApi('sim.acceptQuest', skill);
        if (missing) return missing;
        const npc = w.npcs.filter((n) => n.completableQuests.length > 0 && n.dist <= interact).sort((a, b) => a.dist - b.dist)[0];
        if (!npc) {
          const anyGiver = w.npcs.filter((n) => n.completableQuests.length > 0).sort((a, b) => a.dist - b.dist)[0];
          return anyGiver
            ? `NOT_IN_RANGE: квестодатель ${anyGiver.templateId} в ${anyGiver.dist.toFixed(1)} ярдах (нужно <=${interact}) — нужен navigate`
            : 'NO_GIVER: NPC с доступным проходимым квестом не виден';
        }
        const qid = npc.completableQuests[0];
        const res = (await this.runAction('accept', { questId: qid, playerId: this.lastRaw?.playerId ?? null })) as { ok: boolean; reason?: string; state?: string };
        if (!res?.ok) return `ERROR:accept:${res?.reason ?? 'страница отказала'}`;
        return res.state === 'active'
          ? `OK accept_quest ${qid} у ${npc.templateId} (state=active)`
          : `NO_ACCEPT: игра не отдала квест ${qid} (state=${res.state ?? '?'})`;
      }
      case 'turn_in_quest': {
        const missing = this.requireApi('sim.turnInQuest', skill);
        if (missing) return missing;
        const ready = w.quests.find((q) => q.state === 'ready') ?? null;
        if (!ready) return 'NO_READY_QUEST: готового к сдаче квеста нет';
        const npc = w.npcs.filter((n) => n.templateId === ready.turnInNpcId && n.dist <= interact).sort((a, b) => a.dist - b.dist)[0];
        if (!npc) {
          const far = w.npcs.find((n) => n.templateId === ready.turnInNpcId);
          return far
            ? `NOT_IN_RANGE: ${ready.turnInNpcId} в ${far.dist.toFixed(1)} ярдах — нужен navigate`
            : `NO_TURNIN_NPC: ${ready.turnInNpcId} не виден (нужен navigate по пину карты)`;
        }
        const res = (await this.runAction('turnIn', { questId: ready.id })) as { ok: boolean; reason?: string; state?: string };
        if (!res?.ok) return `ERROR:turn_in:${res?.reason ?? 'страница отказала'}`;
        return res.state === 'done'
          ? `OK turn_in_quest ${ready.id} (state=done)`
          : `NO_TURNIN: игра не приняла ${ready.id} (state=${res.state ?? '?'})`;
      }
      case 'heal': {
        const ability = (this.lastRaw?.abilities ?? []).find((a) => /heal|renew|ward/i.test(a.id) && a.ready);
        if (ability) {
          const res = (await this.runAction('cast', { abilityId: ability.id })) as { ok: boolean; reason?: string };
          if (res?.ok) return `OK heal via ${ability.id}`;
          return `ERROR:heal:${res?.reason ?? 'страница отказала'}`;
        }
        // Без лечения навыком: выход из боя — честная альтернатива, а не «успех».
        if (w.player.inCombat) return 'NO_HEAL_ABILITY: в бою, готового лечения нет — нужен flee';
        if (w.player.hp >= w.player.maxHp) return 'OK heal: hp полное, делать нечего';
        return 'NO_HEAL_ABILITY: готового лечения нет (отдых в офлайне не проверялся)';
      }
      case 'cast_frostbolt':
      case 'cast_fireball': {
        const want = skill === 'cast_frostbolt' ? 'frostbolt' : 'fireball';
        const ability = (this.lastRaw?.abilities ?? []).find((a) => a.id.includes(want));
        if (!ability) return `UNSUPPORTED:${skill}: способности ${want} нет в sim.known (класс/уровень)`;
        if (!ability.ready) return `NO_ABILITY: ${want} на кулдауне ${ability.cooldownLeft.toFixed(1)} с`;
        const res = (await this.runAction('cast', { abilityId: ability.id })) as { ok: boolean; reason?: string };
        return res?.ok ? `OK ${skill} ${ability.id}` : `ERROR:${skill}:${res?.reason ?? 'страница отказала'}`;
      }
      case 'flee': {
        const threat = w.nearby.filter((m) => !m.dead && m.hostile).sort((a, b) => a.dist - b.dist)[0];
        if (!threat) return 'OK flee: угрозы нет';
        const away = Math.atan2(w.player.x - threat.x, w.player.z - threat.z);
        await this.move({ forward: true }, away);
        return `OK flee от ${threat.templateId} (курс ${away.toFixed(2)})`;
      }
      case 'noop':
        await this.move({ stop: true }, null);
        return 'OK noop';
      case 'respawn': {
        const res = (await this.runAction('respawn', {})) as { ok: boolean; reason?: string; via?: string };
        return res?.ok ? `OK respawn via ${res.via}` : `UNSUPPORTED:respawn:${res?.reason ?? 'нет api'}`;
      }
      case 'sell_junk':
      case 'gather':
      case 'craft':
      case 'craft_item':
      case 'equip':
      case 'buy':
        return `UNSUPPORTED:${skill}: не перенесён в браузерную линию (C1.3) — честный отказ, а не «успех»`;
      default:
        return `UNKNOWN_SKILL:${skill}`;
    }
  }

  /** Навигация к точке: тики с гистерезисом, stuck-детектор, честный итог. */
  async navigateTo(
    x: number,
    z: number,
    opts: { maxTicks?: number; arriveYards?: number; sleep?: (ms: number) => Promise<void> } = {},
  ): Promise<{ arrived: boolean; ticks: number; dist: number; reason: string }> {
    const maxTicks = opts.maxTicks ?? 80;
    const arrive = opts.arriveYards ?? 5;
    const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
    const STUCK_TICKS = 4;
    let last: { x: number; z: number } | null = null;
    let still = 0;
    let ticks = 0;
    let dist = Number.POSITIVE_INFINITY;
    for (let i = 0; i < maxTicks; i++) {
      ticks++;
      const value = (await this.evaluate(navStepExpression(x, z, arrive))) as
        | { ok: boolean; reason?: string; arrived?: boolean; d?: number; x?: number; z?: number; fleeing?: boolean }
        | null;
      if (!value || value.ok !== true) {
        return { arrived: false, ticks, dist, reason: `ERROR:navigate:${value?.reason ?? 'страница отказала'}` };
      }
      dist = value.d ?? dist;
      if (value.arrived) return { arrived: true, ticks, dist, reason: 'ARRIVED' };
      if (last && Math.hypot((value.x ?? 0) - last.x, (value.z ?? 0) - last.z) < 0.3) {
        still++;
        if (still >= STUCK_TICKS) {
          return { arrived: false, ticks, dist, reason: `STUCK: не сдвинулись ${still} тиков подряд (dist=${dist.toFixed(1)})` };
        }
      } else {
        still = 0;
      }
      last = { x: value.x ?? 0, z: value.z ?? 0 };
      await sleep(this.navTickMs);
    }
    return { arrived: false, ticks, dist, reason: `TIMEOUT: ${maxTicks} тиков, dist=${dist.toFixed(1)}` };
  }

  /** Один ввод контроллера (поворот/шаг/стоп). `facing=null` — только стоп. */
  async move(input: Record<string, boolean>, facing: number | null): Promise<void> {
    const expr = `(() => {
      const g = window.__game;
      if (!g || !g.controller) return { ok: false, reason: 'no_controller' };
      try {
        ${input.stop ? 'if (typeof g.controller.stop === "function") g.controller.stop();' : `g.controller.move(${JSON.stringify(input)}, ${facing === null ? 'undefined' : facing});`}
        return { ok: true };
      } catch (e) { return { ok: false, reason: String((e && e.message) || e) }; }
    })()`;
    const res = (await this.evaluate(expr)) as { ok: boolean; reason?: string };
    if (!res?.ok) throw new Error(`ПРОВАЛ: ввод контроллера не применён (${res?.reason ?? 'нет ответа'})`);
  }

  private async runAction(kind: Parameters<typeof actionExpression>[0], args: Parameters<typeof actionExpression>[1]): Promise<unknown> {
    return this.evaluate(actionExpression(kind, args));
  }

  close(reason: string): void {
    this.ended = reason;
  }
}

/** Цель для farm: сначала цель квеста (по templateId активных целей), иначе
 *  ближайший враждебный живой моб, которого мы реально можем драться. */
export function pickFarmTarget(w: WorldModel, meleeRange: number): EntityView | null {
  const wanted = new Set<string>();
  for (const q of w.quests) {
    if (q.state !== 'active') continue;
    for (const o of q.objectives) if (o.type === 'kill' && o.targetMobId && o.have < o.required) wanted.add(o.targetMobId);
  }
  const alive = w.nearby.filter((m) => !m.dead && m.hostile && m.hp > 0);
  const questTarget = alive.filter((m) => wanted.has(m.templateId)).sort((a, b) => a.dist - b.dist)[0];
  if (questTarget) return questTarget;
  const inMelee = alive.filter((m) => m.dist <= Math.max(meleeRange * 6, 30)).sort((a, b) => a.dist - b.dist)[0];
  return inMelee ?? null;
}
