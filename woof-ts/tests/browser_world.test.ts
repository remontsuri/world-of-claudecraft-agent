/**
 * Полигон браузерной линии (задача C1.4).
 *
 * Принцип: проверяем НАСТОЯЩИЙ страничный код, а не его пересказ. Выражения из
 * `browser_world.ts` исполняются через `new Function('window','location', …)` против
 * фейкового `window.__game` — тех же объектов (Map для entities/cooldowns, controller,
 * world.players), что живёт в странице. Ни портов, ни серверов, ни браузера:
 * долг J11 замороженной линии (два фейковых CDP и EADDRINUSE в каждом прогоне)
 * закрыт конструкцией — поднимать нечего.
 *
 * Что ловим намеренно (графли эталона, найденные живьём в 2026-08/09):
 *  - `qp.counts` как `required` → «0/0 ACTIVE» на готовом квесте (здесь: counts ≠
 *    resolvedCounts, и required обязан быть из resolvedCounts);
 *  - мёртвая вкладка с тем же URL → честный отказ, а не «работает ни с чем»;
 *  - `controller.face()` no-op → поворот только через move({turnLeft|turnRight});
 *  - единый порог курса → автоколебание (здесь: гистерезис 0.35/0.10 и знак не flipping);
 *  - отсутствие метода страницы → UNSUPPORTED, а не молчаливый «успех».
 */
import { describe, expect, it } from 'vitest';
import {
  BrowserWorld,
  browserCompletable,
  mapSnapshot,
  navStepExpression,
  parseSnapshot,
  pickFarmTarget,
  snapshotExpression,
} from '../src/world/browser_world';
import { acquireLivePage, assertAllowedMethod, livenessExpression, parseCdpFrame, pickGameTarget } from '../src/bridge/cdp_client';
import type { CdpSession, CdpTarget, SessionFactory } from '../src/bridge/cdp_client';
import type { SocketLike } from '../src/bridge/ws_socket';
import { gameFacts, questDef, questOrder } from '../src/facts';
import { buildBrowserAgent } from '../src/core/browser_agent';
import { VIEW_RADIUS, type Counters } from '../src/world/types';

// --- фейковая страница -------------------------------------------------------

interface FakeMob {
  id: number;
  kind: string;
  name: string;
  templateId: string;
  level: number;
  hp: number;
  maxHp: number;
  hostile: boolean;
  dead: boolean;
  lootable?: boolean;
  looted?: boolean;
  inCombat?: boolean;
  aggroTargetId?: number | null;
  x: number;
  z: number;
  questIds?: string[];
  vendorItems?: unknown[];
}

interface FakePageOptions {
  player?: Partial<{ hp: number; maxHp: number; level: number; xp: number; copper: number; facing: number; dead: boolean; inCombat: boolean; x: number; z: number; targetId: number | null; playerClass: string }>;
  mobs?: FakeMob[];
  questStates?: Record<string, string>;
  questLog?: { id: string; state: string; counts: number[]; resolvedCounts: number[] }[];
  abilities?: { id: string; name: string; cooldown?: number; cd?: number; cost?: number; range?: number; passive?: boolean }[];
  inventory?: { id: string; count: number }[];
  /** Каких методов НЕТ (проверка честного UNSUPPORTED). */
  missingApi?: string[];
  /** Живой ли мир (false = мёртвая вкладка). */
  alive?: boolean;
  /** Имитировать бой: автоатака постепенно убивает цель и двигает kill-цели квеста. */
  autoCombat?: boolean;
  /** Сколько тиков страницы нужно, чтобы убить цель (по умолчанию 2). */
  killAfterTicks?: number;
}

interface FakePage {
  evaluate: (expression: string) => Promise<unknown>;
  calls: { method: string; args: unknown[] }[];
  moves: { input: Record<string, boolean>; facing: number | undefined }[];
  state: {
    entities: Map<number, FakeMob>;
    questStates: Record<string, string>;
    accepted: Set<string>;
    logById: Map<string, { id: string; state: string; counts: number[]; resolvedCounts: number[] }>;
    player: Record<string, unknown> & { pos: { x: number; z: number } };
    navTurning: boolean;
  };
  /** Сдвинуть игрока (имитация тика мира). */
  moveTo: (x: number, z: number) => void;
  /** Убить моба (имитация боя). */
  kill: (id: number) => void;
}

function fakePage(opts: FakePageOptions = {}): FakePage {
  const alive = opts.alive !== false;
  const missing = new Set(opts.missingApi ?? []);
  const entities = new Map<number, FakeMob & { pos: { x: number; y: number; z: number } }>();
  // Сущность страницы живёт в `pos`, а не в x/z: фейк обязан быть той же формы.
  for (const m of opts.mobs ?? []) entities.set(m.id, { ...m, pos: { x: m.x, y: 0, z: m.z } });
  const questStates: Record<string, string> = { ...(opts.questStates ?? {}) };
  const questLog = opts.questLog ?? [];
  const p = {
    hp: 100,
    maxHp: 100,
    level: 1,
    xp: 0,
    copper: 0,
    facing: 0,
    dead: false,
    inCombat: false,
    resource: 100,
    maxResource: 100,
    resourceType: 'mana',
    class: 'mage',
    targetId: null as number | null,
    autoAttack: false,
    resting: false,
    cooldowns: new Map<string, number>(),
    inventory: opts.inventory ?? [],
    pos: { x: 0, z: 0 },
    ...(opts.player ?? {}),
  };
  // Страница читает координаты из `p.pos`, а не из `p.x`: фейк обязан быть той же формы.
  p.pos = { x: (p as { x?: number }).x ?? 0, z: (p as { z?: number }).z ?? 0 };
  const calls: { method: string; args: unknown[] }[] = [];
  const moves: { input: Record<string, boolean>; facing: number | undefined }[] = [];
  const win: Record<string, unknown> = {};

  const has = (name: string) => !missing.has(`sim.${name}`);
  const sim: Record<string, unknown> = {
    player: p,
    playerId: 7,
    entities,
    known: (opts.abilities ?? []).map((a) => ({
      def: { id: a.id, name: a.name, passive: !!a.passive, cost: a.cost ?? 0, castTime: 0, cooldown: a.cooldown ?? 0, range: a.range ?? 0 },
      cost: a.cost ?? 0,
      castTime: 0,
      cooldown: a.cooldown ?? 0,
    })),
    bags: [],
    bagCapacity: 16,
    tick: 1,
    time: 12.5,
  };
  // Фейк играет роль ИГРЫ: состояние квеста вычисляется так же авторитетно, как
  // sim.questState в офлайне (available|active|ready|done), а не отдаётся захардкоженным.
  const accepted = new Set<string>();
  const doneSet = new Set<string>();
  const logById = new Map(questLog.map((q) => [q.id, q]));
  if (has('questState'))
    sim.questState = (qid: string) => {
      if (doneSet.has(qid)) return 'done';
      const entry = logById.get(qid);
      if (accepted.has(qid) || entry?.state === 'active' || entry?.state === 'ready') {
        const complete = entry ? entry.counts.every((c, i) => c >= (entry.resolvedCounts[i] ?? c)) : false;
        return complete ? 'ready' : 'active';
      }
      return questStates[qid] ?? 'unavailable';
    };
  if (has('targetEntity'))
    sim.targetEntity = (id: number) => {
      calls.push({ method: 'targetEntity', args: [id] });
      p.targetId = id;
    };
  if (has('startAutoAttack'))
    sim.startAutoAttack = () => {
      calls.push({ method: 'startAutoAttack', args: [] });
      p.autoAttack = true;
    };
  if (has('lootCorpse'))
    sim.lootCorpse = (id: number, pid: number) => {
      calls.push({ method: 'lootCorpse', args: [id, pid] });
      const e = entities.get(id);
      if (e) e.looted = true;
      return { looted: true };
    };
  if (has('acceptQuest'))
    sim.acceptQuest = (qid: string, _x: unknown, pid: number) => {
      calls.push({ method: 'acceptQuest', args: [qid, _x, pid] });
      questStates[qid] = 'active';
      accepted.add(qid);
      // игра заводит запись журнала: counts=0, resolvedCounts — из контента
      if (!logById.has(qid)) {
        let def;
        try {
          def = questDef(qid);
        } catch {
          def = null;
        }
        logById.set(qid, {
          id: qid,
          state: 'active',
          counts: (def?.objectives ?? []).map(() => 0),
          resolvedCounts: (def?.objectives ?? []).map((o) => o.count),
        });
      }
      return true;
    };
  if (has('turnInQuest'))
    sim.turnInQuest = (qid: string) => {
      calls.push({ method: 'turnInQuest', args: [qid] });
      questStates[qid] = 'done';
      doneSet.add(qid);
      return true;
    };
  if (has('interact')) sim.interact = () => calls.push({ method: 'interact', args: [] });
  if (has('entitiesNear')) sim.entitiesNear = () => [...entities.values()];
  if (has('respawn'))
    sim.respawn = () => {
      calls.push({ method: 'respawn', args: [] });
      p.dead = false;
      p.hp = p.maxHp;
    };
  if (has('useAbility'))
    sim.useAbility = (id: string) => {
      calls.push({ method: 'useAbility', args: [id] });
      return true;
    };

  const controller: Record<string, unknown> = {};
  if (!missing.has('controller.move'))
    controller.move = (input: Record<string, boolean>, facing?: number) => {
      moves.push({ input, facing });
      calls.push({ method: 'controller.move', args: [input, facing] });
      if (facing != null) p.facing = facing;
      if (input.forward) {
        // шаг на 1 ярд по курсу (имитация тика мира)
        p.pos.x += Math.sin(p.facing);
        p.pos.z += Math.cos(p.facing);
      }
      if (input.turnLeft) p.facing += 0.4;
      if (input.turnRight) p.facing -= 0.4;
    };
  if (!missing.has('controller.stop'))
    controller.stop = () => {
      calls.push({ method: 'controller.stop', args: [] });
    };
  // face() в офлайне — no-op (проверено эталоном): намеренно ничего не меняем.
  if (!missing.has('controller.face')) controller.face = () => calls.push({ method: 'controller.face', args: [] });

  // Журнал квеста живёт и в sim.questLog, и в world.questLog — как в игре:
  // acceptQuest заводит запись, и снимок обязан её видеть (required/have).
  for (const q of questLog) if (!logById.has(q.id)) logById.set(q.id, q);
  sim.questLog = logById;
  const world = {
    primaryId: 7,
    questLog: logById,
    players: new Map([[7, { equipment: { mainhand: { itemId: 'staff' } }, stats: { kills: 0 } }]]),
  };

  if (alive) {
    win.__game = { sim, controller, world, MOBS: {} };
  } else {
    win.__game = { controller }; // мёртвая вкладка: sim нет
  }
  (win as Record<string, unknown>).__navTurning = false;

  // Имитация боя: цель получает урон каждый тик и умирает, а kill-цели активного
  // квеста двигаются — как в игре. Без этого «farm» не привёл бы к сдаче квеста.
  const hits = new Map<number, number>();
  const killAfter = opts.killAfterTicks ?? 2;
  function tickCombat(): void {
    if (!p.autoAttack || p.targetId == null) return;
    const e = entities.get(p.targetId);
    if (!e || e.dead) return;
    const n = (hits.get(e.id) ?? 0) + 1;
    hits.set(e.id, n);
    if (n < killAfter) {
      e.hp = Math.max(1, e.hp - Math.ceil(e.maxHp / killAfter));
      return;
    }
    hits.delete(e.id);
    e.hp = 0;
    e.dead = true;
    e.lootable = true;
    p.autoAttack = false;
    p.targetId = null;
    for (const entry of logById.values()) {
      if (!accepted.has(entry.id) && entry.state !== 'active' && entry.state !== 'ready') continue;
      let def;
      try {
        def = questDef(entry.id);
      } catch {
        continue;
      }
      def.objectives.forEach((o, i) => {
        if (o.type === 'kill' && o.targetMobId === e.templateId && entry.counts[i] < entry.resolvedCounts[i]) {
          entry.counts[i] += 1;
        }
      });
    }
  }

  const evaluate = async (expression: string): Promise<unknown> => {
    // Страница живёт между вызовами: каждый запрос агента — это тик мира,
    // в котором автоатака доделывает своё дело (иначе бой не сдвинется никогда).
    if (alive && opts.autoCombat !== false) tickCombat();
    // Настоящий страничный код: исполняем исходник против фейкового window.
    const fn = new Function('window', 'location', `return (${expression});`) as (
      w: unknown,
      loc: unknown,
    ) => unknown;
    const value = fn(win, { href: 'http://localhost:5173/' });
    return value instanceof Promise ? await value : value;
  };

  return {
    evaluate,
    calls,
    moves,
    state: {
      entities,
      questStates,
      accepted,
      logById,
      player: p as unknown as FakePage['state']['player'],
      get navTurning() {
        return win.__navTurning as boolean;
      },
    },
    moveTo: (x, z) => {
      p.pos.x = x;
      p.pos.z = z;
    },
    kill: (id) => {
      const e = entities.get(id);
      if (e) {
        e.dead = true;
        e.hp = 0;
        e.lootable = true;
      }
    },
  };
}

const facts = gameFacts();
const zeroCounters: Counters = {
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

/** Квест из контента игры, у которого цель — убийство (для фикстур). */
const killQuest = questOrder.map((id) => ({ id, def: questDef(id) })).find(({ def }) =>
  def.objectives.every((o) => o.type === 'kill' || o.type === 'collect'),
)!;

// --- снимок и его разбор -----------------------------------------------------

describe('снимок страницы → WorldModel', () => {
  it('мёртвая вкладка: честный ПРОВАЛ с подсказкой, а не пустой мир', async () => {
    const page = fakePage({ alive: false });
    const expr = snapshotExpression(questOrder);
    await expect(page.evaluate(expr)).resolves.toMatchObject({ ok: false, reason: 'no_game' });
    const deadValue = await page.evaluate(expr);
    expect(() => parseSnapshot(deadValue)).toThrowError(/no_game/);
    expect(() => parseSnapshot(deadValue)).toThrowError(/Play Offline/);
    expect(() => parseSnapshot(null)).toThrowError(/не объект/);
  });

  it('живая вкладка: игрок, сущности, api, квесты — из страницы, а не из кода', async () => {
    const qid = killQuest.id;
    const page = fakePage({
      player: { hp: 80, maxHp: 120, level: 3, x: 10, z: -4, facing: 0.5, copper: 25, xp: 300 },
      mobs: [
        { id: 11, kind: 'mob', name: 'Wolf', templateId: 'forest_wolf', level: 3, hp: 40, maxHp: 40, hostile: true, dead: false, x: 14, z: -4 },
        { id: 12, kind: 'npc', name: 'Giver', templateId: 'npc_giver', level: 5, hp: 100, maxHp: 100, hostile: false, dead: false, x: 12, z: -4, questIds: [qid] },
        { id: 13, kind: 'mob', name: 'Dead Wolf', templateId: 'forest_wolf', level: 3, hp: 0, maxHp: 40, hostile: true, dead: true, lootable: true, x: 11, z: -4 },
      ],
      questStates: { [qid]: 'available' },
      abilities: [{ id: 'frostbolt', name: 'Frostbolt', cooldown: 8, cd: 0, cost: 10, range: 30 }],
      inventory: [{ id: 'wolf_pelt', count: 3 }],
    });
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder });
    const w = await world.observe();

    expect(w.player.hp).toBe(80);
    expect(w.player.maxHp).toBe(120);
    expect(w.player.level).toBe(3);
    expect(w.player.x).toBe(10);
    expect(w.player.z).toBe(-4);
    expect(w.copper).toBe(25);
    expect(w.nearby.map((m) => m.id)).toContain(11);
    expect(w.corpses.map((c) => c.id)).toEqual([13]);
    expect(w.npcs.map((n) => n.templateId)).toContain('npc_giver');
    const npc = w.npcs.find((n) => n.id === 12)!;
    expect(npc.availableQuests).toEqual([qid]);
    // доступный ≠ проходимый для нас: фильтр обязан быть честным
    expect(npc.completableQuests).toEqual(browserCompletable(qid).ok ? [qid] : []);
    expect(world.countItem('wolf_pelt')).toBe(3);
    expect(world.questState(qid)).toBe('available');
    expect(world.abilities().map((a) => a.id)).toEqual(['frostbolt']);
    expect(world.pageApi['sim.questState']).toBe('function');
    expect(world.capabilities.questStateApi).toBe('full');
    expect(world.capabilities.absoluteCoords).toBe(true);
    expect(world.capabilities.transport).toBe('cdp');
  });

  it('required — из resolvedCounts, НЕ из counts (графль «0/0 ACTIVE»)', async () => {
    const qid = killQuest.id;
    const def = questDef(qid);
    const counts = def.objectives.map(() => 2); // текущий прогресс
    const resolved = def.objectives.map((o) => o.count * 3); // авторитетное required
    const page = fakePage({
      questStates: { [qid]: 'active' },
      questLog: [{ id: qid, state: 'active', counts, resolvedCounts: resolved }],
    });
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder });
    const w = await world.observe();
    const q = w.quests.find((x) => x.id === qid)!;
    expect(q).toBeTruthy();
    q.objectives.forEach((o, i) => {
      expect(o.required).toBe(resolved[i]);
      expect(o.have).toBe(counts[i]);
      expect(o.required).not.toBe(o.have); // именно подмена ломала квесты
    });
  });

  it('available-квест у НЕВИДИМОГО NPC в модель не попадает (не шумим)', async () => {
    const qid = killQuest.id;
    const page = fakePage({ questStates: { [qid]: 'available' }, mobs: [] });
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder });
    const w = await world.observe();
    expect(w.quests.map((q) => q.id)).not.toContain(qid);
    // но состояние игры остаётся доступным напрямую (questStateApi='full')
    expect(world.questState(qid)).toBe('available');
  });

  it('mapSnapshot — чистая функция: тот же вход даёт тот же выход', async () => {
    const page = fakePage({ player: { x: 1, z: 2 }, mobs: [{ id: 5, kind: 'mob', name: 'M', templateId: 'forest_wolf', level: 2, hp: 10, maxHp: 10, hostile: true, dead: false, x: 4, z: 6 }] });
    const raw = parseSnapshot(await page.evaluate(snapshotExpression(questOrder)));
    const a = mapSnapshot(raw, { facts, questIds: questOrder, step: 1, counters: zeroCounters, playerId: 7 });
    const b = mapSnapshot(raw, { facts, questIds: questOrder, step: 1, counters: zeroCounters, playerId: 7 });
    expect(a).toEqual(b);
    expect(a.nearby[0].dist).toBeCloseTo(5);
    expect(Number.isFinite(a.nearby[0].bearing)).toBe(true);
  });
});

// --- действия: только то, что страница реально умеет -------------------------

describe('действия в странице', () => {
  it('нет метода страницы → UNSUPPORTED, а не молчаливый успех', async () => {
    const qid = killQuest.id;
    const page = fakePage({
      missingApi: ['sim.turnInQuest', 'sim.lootCorpse'],
      questStates: { [qid]: 'ready' },
      mobs: [{ id: 21, kind: 'npc', name: 'G', templateId: 'npc_giver', level: 5, hp: 1, maxHp: 1, hostile: false, dead: false, x: 1, z: 0, questIds: [qid] }],
    });
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder });
    const w = await world.observe();
    expect(await world.act('turn_in_quest', w)).toMatch(/^UNSUPPORTED:turn_in_quest: страница не даёт sim\.turnInQuest \(typeof=(undefined|missing)\)/);
    expect(await world.act('loot', w)).toMatch(/^UNSUPPORTED:loot:/);
    expect(await world.act('gather', w)).toMatch(/^UNSUPPORTED:gather:/);
    expect(await world.act('нет_такого', w)).toMatch(/^UNKNOWN_SKILL:/);
    expect(page.calls.map((c) => c.method)).toEqual([]);
  });

  it('farm: цель квеста важнее ближайшего врага; targetEntity + startAutoAttack', async () => {
    const qid = killQuest.id;
    const def = questDef(qid);
    const wanted = def.objectives.find((o) => o.type === 'kill')?.targetMobId ?? 'forest_wolf';
    const page = fakePage({
      questStates: { [qid]: 'active' },
      questLog: [{ id: qid, state: 'active', counts: def.objectives.map(() => 0), resolvedCounts: def.objectives.map((o) => o.count) }],
      mobs: [
        { id: 31, kind: 'mob', name: 'Near', templateId: 'other_mob', level: 2, hp: 10, maxHp: 10, hostile: true, dead: false, x: 2, z: 0 },
        { id: 32, kind: 'mob', name: 'Quest', templateId: wanted, level: 2, hp: 10, maxHp: 10, hostile: true, dead: false, x: 20, z: 0 },
      ],
    });
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder });
    const w = await world.observe();
    const target = pickFarmTarget(w, facts.meleeRange);
    expect(target?.id).toBe(32); // цель квеста, хотя она дальше
    const res = await world.act('farm', w);
    expect(res).toMatch(/^OK farm id=32/);
    expect(page.calls.map((c) => c.method)).toEqual(['targetEntity', 'startAutoAttack']);
  });

  it('accept_quest: вне радиуса — NOT_IN_RANGE (честно), в радиусе — OK и state=active', async () => {
    const qid = killQuest.id;
    // NPC ВИДЕН (в радиусе наблюдения), но до него дальше радиуса взаимодействия:
    // именно это и есть NOT_IN_RANGE. За пределами радиуса вида его бы просто не было.
    const farDist = Math.min(VIEW_RADIUS - 5, Math.max(facts.interactRange * 3, 20));
    const far = fakePage({
      questStates: { [qid]: 'available' },
      mobs: [{ id: 41, kind: 'npc', name: 'G', templateId: 'npc_giver', level: 5, hp: 1, maxHp: 1, hostile: false, dead: false, x: farDist, z: 0, questIds: [qid] }],
    });
    const wFar = new BrowserWorld({ evaluate: far.evaluate, questIds: questOrder });
    expect(await wFar.act('accept_quest', await wFar.observe())).toMatch(/^NOT_IN_RANGE:/);

    const near = fakePage({
      questStates: { [qid]: 'available' },
      mobs: [{ id: 42, kind: 'npc', name: 'G', templateId: 'npc_giver', level: 5, hp: 1, maxHp: 1, hostile: false, dead: false, x: 2, z: 0, questIds: [qid] }],
    });
    const wNear = new BrowserWorld({ evaluate: near.evaluate, questIds: questOrder });
    const res = await wNear.act('accept_quest', await wNear.observe());
    if (browserCompletable(qid).ok) {
      expect(res).toMatch(/^OK accept_quest/);
      expect(near.state.questStates[qid]).toBe('active');
    } else {
      expect(res).toMatch(/^NO_GIVER:/); // квест непроходим для нас — не берём
    }
  });

  it('turn_in_quest: готовый квест у NPC в радиусе → state=done', async () => {
    const qid = killQuest.id;
    const def = questDef(qid);
    const page = fakePage({
      questStates: { [qid]: 'ready' },
      questLog: [{ id: qid, state: 'ready', counts: def.objectives.map((o) => o.count), resolvedCounts: def.objectives.map((o) => o.count) }],
      mobs: [{ id: 51, kind: 'npc', name: 'G', templateId: def.turnInNpcId ?? def.giverNpcId ?? 'npc_giver', level: 5, hp: 1, maxHp: 1, hostile: false, dead: false, x: 2, z: 0, questIds: [qid] }],
    });
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder });
    const w = await world.observe();
    const ready = w.quests.find((q) => q.state === 'ready');
    expect(ready?.id).toBe(qid);
    const res = await world.act('turn_in_quest', w);
    expect(res).toMatch(/^OK turn_in_quest/);
    expect(page.state.questStates[qid]).toBe('done');
  });

  it('cast: способности нет в sim.known → UNSUPPORTED с причиной (класс/уровень)', async () => {
    const page = fakePage({ abilities: [{ id: 'fireball', name: 'Fireball', cooldown: 5, cd: 0 }] });
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder });
    const w = await world.observe();
    expect(await world.act('cast_frostbolt', w)).toMatch(/^UNSUPPORTED:cast_frostbolt: способности frostbolt нет/);
    expect(await world.act('cast_fireball', w)).toMatch(/^OK cast_fireball/);
  });
});

// --- навигация: гистерезис, приход, застревание, побег -----------------------

describe('навигация в странице', () => {
  it('face() — no-op: курс задаётся только move(input, desired)', async () => {
    const page = fakePage({ player: { x: 0, z: 0, facing: 0 } });
    const res = (await page.evaluate(navStepExpression(0, 20))) as { ok: boolean; input: Record<string, boolean>; desired: number };
    expect(res.ok).toBe(true);
    expect(res.input.forward).toBe(true);
    expect(page.moves.length).toBe(1);
    expect(page.moves[0].facing).toBeCloseTo(res.desired);
    expect(page.calls.map((c) => c.method)).not.toContain('controller.face');
  });

  it('гистерезис: |off|<=0.35 — вперёд; во время поворота выход только при |off|<=0.10', async () => {
    const page = fakePage({ player: { x: 0, z: 0, facing: 0 } });
    // цель под 0.2 рад: не поворачиваемся (порог входа 0.35)
    const target = { x: Math.sin(0.2) * 20, z: Math.cos(0.2) * 20 };
    const first = (await page.evaluate(navStepExpression(target.x, target.z))) as { input: Record<string, boolean> };
    expect(first.input.forward).toBe(true);
    expect(first.input.turnLeft).toBeUndefined();
    // цель под 1.0 рад: поворот влево (off>0)
    const t2 = { x: Math.sin(1.0) * 20, z: Math.cos(1.0) * 20 };
    page.moveTo(0, 0);
    page.state.player.facing = 0;
    const second = (await page.evaluate(navStepExpression(t2.x, t2.z))) as { input: Record<string, boolean>; off: number };
    expect(second.off).toBeCloseTo(1.0, 5);
    expect(second.input.turnLeft).toBe(true);
    expect(second.input.forward).toBe(true); // |off| <= 1.20 — идём, доворачивая
    // теперь мы «поворачиваем»: off 0.2 > 0.10 → ПРОДОЛЖАЕМ поворот (нет автоколебания)
    page.state.player.facing = 0;
    const third = (await page.evaluate(navStepExpression(target.x, target.z))) as { input: Record<string, boolean> };
    expect(third.input.turnLeft).toBe(true);
    // знак не flipping при том же off → камера не дёргается
    page.state.player.facing = 0;
    const fourth = (await page.evaluate(navStepExpression(target.x, target.z))) as { input: Record<string, boolean> };
    expect(fourth.input.turnLeft).toBe(true);
  });

  it('приход: d < 5 → arrived + controller.stop, ввода движения нет', async () => {
    const page = fakePage({ player: { x: 0, z: 0 } });
    const res = (await page.evaluate(navStepExpression(1, 1))) as { arrived: boolean; d: number };
    expect(res.arrived).toBe(true);
    expect(res.d).toBeLessThan(5);
    expect(page.calls.map((c) => c.method)).toContain('controller.stop');
    expect(page.moves.length).toBe(0);
  });

  it('побег: в бою при hp<50% бежим ОТ ближайшего врага (leash), а не сквозь пачку', async () => {
    const page = fakePage({
      player: { x: 0, z: 0, hp: 30, maxHp: 100, inCombat: true, facing: 0 },
      mobs: [{ id: 61, kind: 'mob', name: 'W', templateId: 'forest_wolf', level: 2, hp: 20, maxHp: 20, hostile: true, dead: false, x: 3, z: 0 }],
    });
    const res = (await page.evaluate(navStepExpression(0, 50))) as { fleeing: boolean; input: Record<string, boolean>; facing?: number };
    expect(res.fleeing).toBe(true);
    expect(res.input.forward).toBe(true);
    const applied = page.moves[0].facing!;
    // курс ОТ моба: моб в +x, значит бежим в -x
    expect(Math.sin(applied)).toBeLessThan(0);
  });

  it('navigateTo: застревание честное (STUCK), приход — ARRIVED, без реальных таймеров', async () => {
    const stuck = fakePage({ player: { x: 0, z: 0 } });
    const wStuck = new BrowserWorld({ evaluate: async (expr) => {
      // игрок не двигается: controller.move ничего не меняет
      return stuck.evaluate(expr);
    }, navTickMs: 0 });
    const noMove = { evaluate: async (expr: string) => {
      const value = await stuck.evaluate(expr);
      return value;
    } };
    void noMove;
    const stuckWorld = new BrowserWorld({ evaluate: stuck.evaluate, navTickMs: 0 });
    // цель далеко, а страница не двигает игрока (фейк двигает, поэтому ломаем ввод)
    const frozenPage = fakePage({ player: { x: 0, z: 0 }, missingApi: ['controller.move'] });
    const w2 = new BrowserWorld({ evaluate: frozenPage.evaluate, navTickMs: 0 });
    const r2 = await w2.navigateTo(200, 200, { maxTicks: 10, sleep: async () => undefined });
    expect(r2.arrived).toBe(false);
    expect(r2.reason).toMatch(/ERROR:navigate|STUCK|TIMEOUT/);

    const near = fakePage({ player: { x: 0, z: 0 } });
    const w3 = new BrowserWorld({ evaluate: near.evaluate, navTickMs: 0 });
    const r3 = await w3.navigateTo(2, 2, { maxTicks: 5, sleep: async () => undefined });
    expect(r3.arrived).toBe(true);
    expect(r3.reason).toBe('ARRIVED');
    void stuck;
    void wStuck;
  });
});

// --- счётчики: что авторитетно, а что наблюдаемо -----------------------------

describe('счётчики браузерного мира', () => {
  it('quests_done — авторитетно по questState; deaths — по переходу dead', async () => {
    const qid = killQuest.id;
    const page = fakePage({ questStates: { [qid]: 'done' } });
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder });
    await world.observe();
    expect(world.counters.questsCompleted).toBe(1);
    expect(world.counters.deaths).toBe(0);
    page.state.player.dead = true;
    await world.observe();
    expect(world.counters.deaths).toBe(1);
    await world.observe();
    expect(world.counters.deaths).toBe(1); // переход, а не «мертв каждый кадр»
  });

  it('kills — наблюдаемый переход alive→dead в бою + сверка с kill-целями квеста', async () => {
    const qid = killQuest.id;
    const def = questDef(qid);
    const wanted = def.objectives.find((o) => o.type === 'kill')?.targetMobId ?? 'forest_wolf';
    const page = fakePage({
      player: { inCombat: true },
      questStates: { [qid]: 'active' },
      questLog: [{ id: qid, state: 'active', counts: def.objectives.map(() => 0), resolvedCounts: def.objectives.map((o) => o.count) }],
      mobs: [{ id: 71, kind: 'mob', name: 'W', templateId: wanted, level: 2, hp: 10, maxHp: 10, hostile: true, dead: false, x: 3, z: 0 }],
    });
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder });
    await world.observe();
    expect(world.counters.kills).toBe(0);
    page.kill(71);
    await world.observe();
    expect(world.counters.kills).toBe(1);
    // журнал квеста权威нее наблюдения: если игра засчитала 3 убийства — верим журналу
    page.state.questStates[qid] = 'active';
    const log = (page as unknown as { state: { questStates: Record<string, string> } }).state;
    void log;
    const second = fakePage({
      player: { inCombat: true },
      questStates: { [qid]: 'active' },
      questLog: [{ id: qid, state: 'active', counts: def.objectives.map((o) => (o.type === 'kill' ? 3 : 0)), resolvedCounts: def.objectives.map((o) => o.count) }],
      mobs: [{ id: 72, kind: 'mob', name: 'W', templateId: wanted, level: 2, hp: 10, maxHp: 10, hostile: true, dead: false, x: 3, z: 0 }],
    });
    const w2 = new BrowserWorld({ evaluate: second.evaluate, questIds: questOrder });
    await w2.observe();
    await w2.observe();
    expect(w2.counters.kills).toBeGreaterThanOrEqual(3);
  });
});

// --- транспорт: выбор живой вкладки и запрещённые методы ----------------------

interface FakeSocket extends SocketLike {
  readyState: number;
  send: (data: string) => void;
  close: () => void;
  onOpen: (cb: () => void) => void;
  onClose: (cb: (code: number, reason: string) => void) => void;
  onError: (cb: (message: string) => void) => void;
  onMessage: (cb: (text: string) => void) => void;
}

function fakeSocket(handler: (frame: { id?: number; method?: string; params?: unknown }) => unknown): FakeSocket {
  let onMsg: ((text: string) => void) | null = null;
  return {
    readyState: 1,
    send: (data: string) => {
      const frame = JSON.parse(data) as { id?: number; method?: string; params?: unknown };
      const result = handler(frame);
      if (onMsg && frame.id != null) onMsg(JSON.stringify({ id: frame.id, result }));
    },
    close: () => undefined,
    onOpen: () => undefined,
    onClose: () => undefined,
    onError: () => undefined,
    onMessage: (cb) => {
      onMsg = cb;
    },
  };
}

describe('транспорт CDP', () => {
  it('запрещённые методы блокируются структурно (страницу не перезагружаем)', () => {
    for (const m of ['Page.reload', 'Page.navigate', 'Input.dispatchKeyEvent', 'Browser.close', 'Target.closeTarget']) {
      expect(() => assertAllowedMethod(m)).toThrowError(/запрещён/);
    }
    expect(() => assertAllowedMethod('Runtime.evaluate')).not.toThrow();
  });

  it('кадр CDP не JSON — ПРОВАЛ, а не пропуск (иначе ожидание повиснет)', () => {
    expect(() => parseCdpFrame('не json')).toThrowError(/не JSON/);
    expect(() => parseCdpFrame('[1,2]')).toThrowError(/не объект/);
    expect(parseCdpFrame('{"id":1,"result":{}}')).toEqual({ id: 1, result: {} });
  });

  it('pickGameTarget: ноль кандидатов и несколько — ПРОВАЛ, не угадываем', () => {
    const t = (id: string, url: string, type = 'page'): CdpTarget => ({ id, type, title: url, url, webSocketDebuggerUrl: `ws://x/${id}` });
    expect(pickGameTarget([t('a', 'http://localhost:5173/')]).id).toBe('a');
    expect(() => pickGameTarget([t('b', 'http://example.com')])).toThrowError(/нет страницы с '5173'/);
    expect(() => pickGameTarget([t('c', 'http://localhost:5173/'), t('d', 'http://localhost:5173/other')])).toThrowError(/не угадываем/);
  });

  it('зонд живости: мёртвая вкладка — live:false с причиной', async () => {
    const dead = fakePage({ alive: false });
    const res = (await dead.evaluate(livenessExpression())) as { live: boolean; reason: string };
    expect(res.live).toBe(false);
    expect(res.reason).toMatch(/без sim/);
    const live = fakePage({ player: { hp: 55, level: 4, x: 1, z: 2 } });
    const ok = (await live.evaluate(livenessExpression())) as { live: boolean; hp: number; level: number; primaryId: number };
    expect(ok.live).toBe(true);
    expect(ok.hp).toBe(55);
    expect(ok.level).toBe(4);
    expect(ok.primaryId).toBe(7);
  });

  it('acquireLivePage: мёртвая вкладка идёт ПЕРВОЙ — выбирается живая (J4)', async () => {
    const dead = fakePage({ alive: false });
    const live = fakePage({ player: { hp: 42, level: 2 } });
    const targets: CdpTarget[] = [
      { id: 'dead', type: 'page', title: 'World of ClaudeCraft', url: 'http://localhost:5173/', webSocketDebuggerUrl: 'ws://dead' },
      { id: 'live', type: 'page', title: 'World of ClaudeCraft', url: 'http://localhost:5173/?world', webSocketDebuggerUrl: 'ws://live' },
    ];
    const byUrl: Record<string, FakePage> = { 'ws://dead': dead, 'ws://live': live };
    const open: SessionFactory = async (wsUrl) => {
      const page = byUrl[wsUrl];
      const socket = fakeSocket((frame) => {
        if (frame.method === 'Runtime.evaluate') {
          const expr = (frame.params as { expression: string }).expression;
          // синхронно исполняем страничный код и отдаём его как CDP-ответ
          const fn = new Function('return (' + expr + ');') as () => unknown;
          const value = fn.call({ window: page });
          return { result: { value: value instanceof Promise ? undefined : value } };
        }
        return {};
      });
      // для async-выражений нужен настоящий await: делаем его через microtask
      const session = new (await import('../src/bridge/cdp_client')).CdpSession(socket);
      const origEvaluate = session.evaluate.bind(session);
      session.evaluate = async (expression: string) => {
        void origEvaluate;
        return page.evaluate(expression);
      };
      return session as CdpSession;
    };
    const fetchImpl = (async () => ({ ok: true, status: 200, statusText: 'OK', json: async () => targets })) as unknown as typeof fetch;
    const acquired = await acquireLivePage({ cdpBase: 'http://127.0.0.1:9222', urlHint: '5173', fetchImpl, open });
    expect(acquired.target.id).toBe('live');
    expect(acquired.probe.live).toBe(true);
    expect(acquired.probes.filter((p) => !p.live).map((p) => p.targetId)).toEqual(['dead']);
    acquired.session.close();
  });

  it('две живые вкладки — ПРОВАЛ с требованием --target-id', async () => {
    const a = fakePage({ player: { hp: 10 } });
    const b = fakePage({ player: { hp: 20 } });
    const targets: CdpTarget[] = [
      { id: 'a', type: 'page', title: 'A', url: 'http://localhost:5173/', webSocketDebuggerUrl: 'ws://a' },
      { id: 'b', type: 'page', title: 'B', url: 'http://localhost:5173/x', webSocketDebuggerUrl: 'ws://b' },
    ];
    const byUrl: Record<string, FakePage> = { 'ws://a': a, 'ws://b': b };
    const open: SessionFactory = async (wsUrl) => {
      const page = byUrl[wsUrl];
      const session = new (await import('../src/bridge/cdp_client')).CdpSession(fakeSocket(() => ({})));
      session.evaluate = async (expression: string) => page.evaluate(expression);
      return session as CdpSession;
    };
    const fetchImpl = (async () => ({ ok: true, status: 200, statusText: 'OK', json: async () => targets })) as unknown as typeof fetch;
    await expect(acquireLivePage({ fetchImpl, open })).rejects.toThrowError(/живых вкладок 2/);
    const chosen = await acquireLivePage({ targetId: 'b', fetchImpl, open });
    expect(chosen.target.id).toBe('b');
    chosen.session.close();
  });

  it('ни одной живой вкладки — честный список причин', async () => {
    const dead = fakePage({ alive: false });
    const targets: CdpTarget[] = [{ id: 'd', type: 'page', title: 'D', url: 'http://localhost:5173/', webSocketDebuggerUrl: 'ws://d' }];
    const open: SessionFactory = async () => {
      const session = new (await import('../src/bridge/cdp_client')).CdpSession(fakeSocket(() => ({})));
      session.evaluate = async (expression: string) => dead.evaluate(expression);
      return session as CdpSession;
    };
    const fetchImpl = (async () => ({ ok: true, status: 200, statusText: 'OK', json: async () => targets })) as unknown as typeof fetch;
    await expect(acquireLivePage({ fetchImpl, open })).rejects.toThrowError(/ЖИВОЙ среди них нет/);
  });
});

// --- приёмка C1.6 = J8 на полигоне (без браузера, без портов) ----------------

describe('приёмка C1.6=J8 на полигоне', () => {
  const killOnly = questOrder
    .map((id) => ({ id, def: questDef(id) }))
    .filter(({ def }) => def.objectives.length > 0 && def.objectives.every((o) => o.type === 'kill'))
    .filter(({ id }) => browserCompletable(id).ok)[0];

  it('в контенте игры есть квест «только убийства», который мы честно берём', () => {
    expect(killOnly, 'без квеста на убийства приёмка J8 невыполнима: нечего считать в kills').toBeTruthy();
    expect(killOnly.def.objectives[0].targetMobId, 'у квеста на убийства обязан быть targetMobId').toBeTruthy();
  });

  it('цикл «взять квест → убить → сдать»: kills>=1 И quests_done>=1 (пороги J8, объявлены заранее)', async () => {
    const { id: qid, def } = killOnly;
    const need = def.objectives.reduce((s, o) => s + o.count, 0);
    const mobId = def.objectives[0].targetMobId as string;
    const giverId = def.giverNpcId ?? 'quest_giver';
    const turnInId = def.turnInNpcId ?? giverId;
    const mobs: FakeMob[] = [
      { id: 900, kind: 'npc', name: 'Giver', templateId: giverId, level: 5, hp: 1, maxHp: 1, hostile: false, dead: false, x: 3, z: 0, questIds: [qid] },
    ];
    if (turnInId !== giverId) {
      mobs.push({ id: 899, kind: 'npc', name: 'TurnIn', templateId: turnInId, level: 5, hp: 1, maxHp: 1, hostile: false, dead: false, x: -3, z: 0, questIds: [qid] });
    }
    for (let i = 0; i < need + 2; i++) {
      mobs.push({ id: 1000 + i, kind: 'mob', name: 'Mob', templateId: mobId, level: 3, hp: 20, maxHp: 20, hostile: true, dead: false, x: 5 + i, z: i % 3 });
    }
    const page = fakePage({
      player: { hp: 400, maxHp: 400, level: 3, x: 0, z: 0 },
      mobs,
      questStates: { [qid]: 'available' },
      autoCombat: true,
      killAfterTicks: 1,
    });
    const dbg = !!process.env.WOOF_DEBUG;
    const out = dbg ? (s: string) => console.log(s) : () => undefined;
    const world = new BrowserWorld({ evaluate: page.evaluate, questIds: questOrder, navTickMs: 0, log: out });
    const agent = buildBrowserAgent(world, { sleep: async () => undefined, log: out, navMaxTicks: 40, verbose: dbg, logEvery: dbg });
    const s = await agent.run(150);

    // Пороги J8 — те же, что объявлены в run_offline.ts по умолчанию.
    expect(s.kills, `kills при пороге 1; фаза=${s.phase} ended=${s.ended}`).toBeGreaterThanOrEqual(1);
    expect(s.questsDone, `quests_done при пороге 1; сдано=${JSON.stringify(s.turnIns)}`).toBeGreaterThanOrEqual(1);
    expect(s.turnIns.map((t) => t.questId)).toContain(qid);
    expect(s.firstTurnInStep).toBeGreaterThan(0);
    expect(page.state.accepted.has(qid)).toBe(true);
    expect(s.deaths).toBe(0);
    // Не «все методы страницы на месте» (их может и не быть), а ровно те, без
    // которых приёмка J8 невозможна в принципе: иначе тест врёт о готовности.
    for (const m of ['sim.targetEntity', 'sim.startAutoAttack', 'sim.acceptQuest', 'sim.turnInQuest', 'sim.questState', 'sim.lootCorpse', 'controller.move']) {
      expect(world.pageApi[m], `без ${m} агент не может ни драться, ни сдать квест`).toBe('function');
    }
    expect(Object.keys(s.unknownKinds)).toEqual([]);
  }, 120_000);
});
