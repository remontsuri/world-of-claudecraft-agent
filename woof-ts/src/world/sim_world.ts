/**
 * sim_world.ts — единственный источник мира. Никакого браузера, CDP и HTTP-моста.
 *
 * Наблюдение — богатое: читаем `Sim` игры напрямую (сущности, квесты, счётчики),
 * как это делал browser_bridge через `window.__game.sim`, только без браузера.
 * Действие — каноническое: исключительно `applyAction(sim, idx)` из `src/sim/obs`,
 * то есть те же 61 ACTIONS, что и у RL-обвязки upstream. Так агент не получает
 * возможностей, которых нет у sanctioned action space, и не изобретает свои.
 *
 * Детерминизм: мир воспроизводим от (seed, gathererIdentity); wall-clock и
 * Math.random не используются (правило upstream headless/CLAUDE.md).
 *
 * Игра: World of ClaudeCraft (levy-street), MIT. Исходники игры не меняем.
 */
import { allocateHeadlessGathererIdentity } from '../../game/headless/gatherer_identity';
import { CLASSES, QUESTS } from '../../game/src/sim/data';
import { ACTIONS, applyAction, encodeObs, NUM_ACTIONS } from '../../game/src/sim/obs';
import { Sim } from '../../game/src/sim/sim';
import { angleTo, dist2d, MAX_LEVEL, normAngle } from '../../game/src/sim/types';
import { gameFacts, npcPins, type NpcPin, type QuestDef } from '../facts';
import { predictedUsefulAccept } from './quest_policy';
import type { World, WorldCapabilities } from './world';
import type { MapPin } from './types';
import {
  activeQuest,
  type Counters,
  type EntityView,
  type ObjectiveView,
  type PlayerView,
  type QuestStateName,
  type QuestView,
  readyQuest,
  VIEW_RADIUS,
  type WorldModel,
} from './types';

/** Размер блока "self" в obs: единственная константа раскладки, которую мы
 *  называем сами (obs.ts его не экспортирует). Инвариант всей раскладки
 *  зафиксирован тестом tests/facts.test.ts: если игра изменит блок, obsSize()
 *  перестанет сходиться с формулой и тест упадёт громко, а не молча. */
export const OBS_SELF_BLOCK = 16;

/** Идентичность headless-сборщика (детерминизм мира зависит и от неё). */
export type GathererIdentity = ReturnType<typeof allocateHeadlessGathererIdentity>;

/** Статические пины NPC (контент игры) — быстрый поиск по шаблону. */
const PIN_BY_ID: Map<string, NpcPin> = new Map(npcPins().map((p) => [p.templateId, p]));

export interface WorldOptions {
  seed: number;
  playerClass?: string;
  playerLevel?: number;
  /** Тиков симуляции на одно решение агента (у upstream env по умолчанию 5). */
  frameSkip?: number;
  /** 0 = без ограничения. */
  maxSteps?: number;
  /** Фиксированная идентичность — для воспроизводимых тестов. */
  gathererIdentity?: GathererIdentity;
  respawnSeconds?: number;
  /**
   * Радиус наблюдения NPC, ярды. 0 = без ограничения (по умолчанию).
   * Заявленная политика, а не «подглядывание»: NPC и их список квестов — это
   * аналог карты и журнала квестов, которые у игрока есть всегда. Боевое
   * наблюдение (мобы, трупы, объекты) при этом ограничено VIEW_RADIUS=60 —
   * ровно как в RL-obs игры (obs.ts: d < 60). Строгий режим: --npc-view 60.
   */
  /** Радиус видимости NPC как ЖИВЫХ сущностей. По умолчанию = VIEW_RADIUS (60),
   *  то есть NPC наблюдаются ровно как мобы/объекты — так же устроен живой мир:
   *  клиент получает сущности только в радиусе интереса
   *  (PLAYER_INTEREST_DROP_RADIUS=100, src/sim/types.ts:56; headless env держит
   *  собственный throttle 80, headless/env_server.ts:120). Значение 0 — явная
   *  ПРИВИЛЕГИЯ СТЕНДА (неограниченная видимость NPC): допустима только для
   *  диагностики, печатается до прогона и пишется в evidence.
   *  Знание «где на карте квестодатель» при этом не пропадает: оно живёт в слое
   *  карты (WorldModel.mapPins) и берётся из статического контента игры. */
  npcViewRadius?: number;
}

export interface AbilityView {
  slot: number;
  id: string;
  ready: boolean;
  cooldownFrac: number;
}

export interface StepResult {
  action: string;
  actionIndex: number;
  step: number;
  counters: Counters;
  delta: Partial<Counters>;
  terminated: boolean;
  truncated: boolean;
}

interface RawEntity {
  id: number;
  kind: string;
  templateId?: string;
  name?: string;
  level?: number;
  hp?: number;
  maxHp?: number;
  hostile?: boolean;
  dead?: boolean;
  lootable?: boolean;
  questIds?: string[];
  aggroTargetId?: number | null;
  facing?: number;
  pos: { x: number; y?: number; z: number };
}

export class SimWorld implements World {
  private readonly sim: Sim;
  private readonly raw: any;
  private stepCount = 0;
  private prevCounters: Counters;
  private lastModel: WorldModel | null = null;
  private endedReason: string | null = null;

  readonly facts = gameFacts();
  readonly opts: Required<Omit<WorldOptions, 'gathererIdentity'>> & {
    gathererIdentity: GathererIdentity;
  };
  private constructor(sim: Sim, opts: WorldOptions) {
    this.sim = sim;
    this.raw = sim as any;
    this.opts = {
      seed: opts.seed,
      playerClass: opts.playerClass ?? 'warrior',
      playerLevel: opts.playerLevel ?? 1,
      frameSkip: opts.frameSkip ?? 5,
      maxSteps: opts.maxSteps ?? 0,
      respawnSeconds: opts.respawnSeconds ?? 15,
      npcViewRadius: opts.npcViewRadius ?? VIEW_RADIUS,
      gathererIdentity: opts.gathererIdentity ?? allocateHeadlessGathererIdentity(),
    };
    if (this.opts.playerLevel !== 1) this.raw.setPlayerLevel(this.opts.playerLevel);
    this.prevCounters = { ...this.counters };
  }

  /** Новый мир: тот же Sim, что и в headless env server upstream. */
  static create(opts: WorldOptions): SimWorld {
    const playerClass = opts.playerClass ?? 'warrior';
    if (!Object.keys(CLASSES).includes(playerClass)) {
      throw new Error(
        `неизвестный класс "${playerClass}"; доступны: ${Object.keys(CLASSES).join(', ')}`,
      );
    }
    // Уровень нормализуем ДО проверки: setPlayerLevel(undefined) даёт level=NaN,
    // а вместе с ним NaN в hp/maxHp — молчаливая порча всего наблюдения.
    const playerLevel = opts.playerLevel ?? 1;
    if (!Number.isInteger(playerLevel) || playerLevel < 1 || playerLevel > MAX_LEVEL) {
      throw new Error(`playerLevel обязан быть целым 1..${MAX_LEVEL}, получено: ${String(opts.playerLevel)}`);
    }
    const sim = new Sim({
      seed: opts.seed,
      playerClass: playerClass as any,
      respawnSeconds: opts.respawnSeconds ?? 15,
      autoEquip: true,
      idleMobTickRadius: 80,
      gathererIdentity: opts.gathererIdentity ?? allocateHeadlessGathererIdentity(),
    } as any);
    const world = new SimWorld(sim, { ...opts, playerClass, playerLevel });
    const hp = world.observe().player.hp;
    if (!Number.isFinite(hp) || hp <= 0) {
      throw new Error(`мир создан, но hp игрока не число (${hp}) — создание мира сломано, продолжать нельзя`);
    }
    return world;
  }

  get actions(): readonly string[] {
    return ACTIONS as readonly string[];
  }

  get step(): number {
    return this.stepCount;
  }

  get ended(): string | null {
    return this.endedReason;
  }

  /** Индекс действия по имени. Незнание — исключение, а не молчаливый noop. */
  actionIndex(name: string): number {
    const idx = (ACTIONS as readonly string[]).indexOf(name);
    if (idx < 0) {
      throw new Error(
        `в игре нет действия "${name}" (доступно ${NUM_ACTIONS}: ${ACTIONS.slice(0, 12).join(', ')}, ...)`,
      );
    }
    return idx;
  }

  get counters(): Counters {
    const c = this.raw.counters;
    return {
      kills: c.kills,
      deaths: c.deaths,
      questsCompleted: c.questsCompleted,
      questProgress: c.questProgress,
      xpGained: c.xpGained,
      levelUps: c.levelUps,
      damageDealt: c.damageDealt,
      damageTaken: c.damageTaken,
      lootCopper: c.lootCopper,
    };
  }

  get copper(): number {
    return this.raw.copper ?? 0;
  }

  /** Объявленные возможности стенда: in-process Sim даёт всё, живой мир — не всё. */
  get capabilities(): WorldCapabilities {
    return {
      transport: 'in-process',
      absoluteCoords: true,
      questStateApi: 'full',
      itemCountApi: true,
      contentData: true,
      deterministic: true,
      frameSkip: this.opts.frameSkip,
      realtime: false,
      otherPlayers: false,
      // Headless RL-стенд беднее онлайн-мира: `targetNearest` в src/world_api.ts игры
      // помечен как dispatch-only RL-токен (по проводу не ходит), а в словаре команд
      // `COMMAND_NAMES` того же файла есть `target`/`tab` (свободный выбор цели),
      // `abandon` (отказ от квеста) и `buy`/`sell` (продавец). Возможности живого мира
      // выводятся из этой таблицы, а не объявляются на глаз: liveWorldCapabilities()
      // в src/bridge/ws_protocol.ts. Про груп-лут честно: фасет IWorldLoot.submitLootRoll
      // в upstream есть, а токена команды в COMMAND_NAMES v0.43.2 не нашлось — поэтому
      // partyLootRolls выводится поиском токенов (lootRollTokens()), а не утверждается.
      targetSelection: 'nearest-only',
      abandonQuest: false,
      vendor: false,
      partyLootRolls: false,
      commandVocabulary: 'rl-actions',
      entityIdentity: 'stable',
      entityTemplates: true,
      entityAbsoluteHp: true,
      damageCounters: true,
      questObjectiveCounts: true,
      latencyMs: 0,
    };
  }

  /** Сколько экземпляров предмета у игрока — публичный API игры (Sim.countItem).
   *  Нужен, чтобы отличать «лут не удался» от «лут удался, но труп ещё не пуст». */
  countItem(itemId: string): number {
    if (!this.capabilities.itemCountApi) {
      throw new Error('мир не предоставляет число предметов (itemCountApi=false) — молчаливого 0 не будет');
    }
    const n = (this.raw as unknown as { countItem: (id: string) => number }).countItem(itemId);
    return Number.isFinite(n) ? n : 0;
  }

  /** Одно решение агента: действие + frameSkip тиков мира (как в env server). */
  stepAction(action: string | number): StepResult {
    if (this.endedReason) {
      throw new Error(`эпизод завершён (${this.endedReason}); дальнейшие шаги невозможны`);
    }
    const idx = typeof action === 'number' ? action : this.actionIndex(action);
    const name = typeof action === 'number' ? (ACTIONS[action] ?? `#${action}`) : action;
    const before = this.counters;
    applyAction(this.sim, idx);
    for (let i = 0; i < this.opts.frameSkip; i++) this.raw.tick();
    this.stepCount++;
    const after = this.counters;
    this.prevCounters = before;

    const delta: Partial<Counters> = {};
    for (const k of Object.keys(after) as (keyof Counters)[]) {
      if (after[k] !== before[k]) delta[k] = after[k] - before[k];
    }

    // Смерть эпизод не заканчивает: applyAction сам воскрешает у Spirit Healer
    // (obs.ts), а deaths растёт и виден в отчёте. Заканчивают — кап уровня и maxSteps.
    const terminated = this.raw.player.level >= MAX_LEVEL;
    const truncated = this.opts.maxSteps > 0 && this.stepCount >= this.opts.maxSteps;
    if (terminated) this.endedReason = 'terminated: достигнут максимальный уровень';
    else if (truncated) this.endedReason = `truncated: maxSteps=${this.opts.maxSteps}`;

    return { action: name, actionIndex: idx, step: this.stepCount, counters: after, delta, terminated, truncated };
  }

  /** Текущее наблюдение. Мир не продвигает: читать состояние можно в любой момент. */
  observe(): WorldModel {
    const p = this.raw.player as RawEntity & Record<string, any>;
    const player: PlayerView = {
      hp: p.hp ?? 0,
      maxHp: p.maxHp ?? 0,
      resource: p.resource ?? 0,
      maxResource: p.maxResource ?? 0,
      resourceType: String(p.resourceType ?? ''),
      level: p.level ?? 1,
      xp: this.raw.xp ?? 0,
      x: p.pos.x,
      z: p.pos.z,
      facing: p.facing ?? 0,
      dead: !!p.dead,
      inCombat: !!p.inCombat,
      autoAttack: !!p.autoAttack,
      resting: !!(p.sitting || p.eating || p.drinking),
      playerClass: String(this.opts.playerClass),
      targetId: p.targetId ?? null,
    };

    const nearby: EntityView[] = [];
    const npcs: EntityView[] = [];
    const objects: EntityView[] = [];
    const corpses: EntityView[] = [];
    let target: EntityView | null = null;

    // NPC видим по политике npcViewRadius (0 = как карта: всегда), остальное —
    // строго в VIEW_RADIUS=60, как в RL-наблюдении игры.
    const npcRadius = this.opts.npcViewRadius > 0 ? this.opts.npcViewRadius : Number.POSITIVE_INFINITY;
    this.refreshNpcQuestCache();

    for (const e of this.raw.entities.values() as Iterable<RawEntity>) {
      if (e.kind === 'player') continue;
      const d = dist2d(p.pos as any, e.pos as any);
      if (d > (e.kind === 'npc' ? npcRadius : VIEW_RADIUS)) continue;
      const view = this.toView(e, p, d);
      if (e.id === player.targetId) target = view;
      if (e.kind === 'mob') {
        if (e.dead) {
          if (e.lootable) corpses.push(view);
        } else if (e.hostile) nearby.push(view);
      } else if (e.kind === 'npc') {
        npcs.push(view);
      } else if (e.kind === 'object') {
        objects.push(view);
      }
    }
    nearby.sort((a, b) => a.dist - b.dist);
    corpses.sort((a, b) => a.dist - b.dist);
    npcs.sort((a, b) => a.dist - b.dist);
    objects.sort((a, b) => a.dist - b.dist);

    const model: WorldModel = {
      step: this.stepCount,
      time: this.raw.time ?? 0,
      player,
      target,
      nearby,
      npcs,
      objects,
      corpses,
      // Журнал квестов + то, что можно взять рядом (NPC в пределах VIEW_RADIUS):
      // список всех доступных квестов мира агенту не нужен и только шумит.
      quests: this.questViews(npcs.filter((n) => n.dist <= VIEW_RADIUS)),
      mapPins: this.buildMapPins(p.pos.x, p.pos.z),
      counters: this.counters,
      copper: this.raw.copper ?? 0,
    };
    this.lastModel = model;
    return model;
  }

  get lastObservation(): WorldModel | null {
    return this.lastModel;
  }

  /** Способности игрока: готовность берём из собственного расчёта игры (encodeObs),
   *  а не пересчитываем руками — там ~30 условий (ресурс, GCD, ауры, девоция...). */
  abilities(): AbilityView[] {
    const obs = encodeObs(this.sim);
    const known = (this.raw.known ?? []) as { def: { id: string } }[];
    const out: AbilityView[] = [];
    for (let i = 0; i < this.facts.abilitySlots; i++) {
      const off = OBS_SELF_BLOCK + i * 2;
      out.push({
        slot: i,
        id: known[i]?.def.id ?? `slot_${i + 1}`,
        ready: obs[off] > 0.5,
        cooldownFrac: obs[off + 1] ?? 0,
      });
    }
    return out;
  }

  /** Только для диагностики и тестов: внутренний объект игры. */
  debugSim(): any {
    return this.raw;
  }

  private toView(e: RawEntity, p: RawEntity, d: number): EntityView {
    const view: EntityView = {
      id: e.id,
      kind: e.kind as EntityView['kind'],
      templateId: String(e.templateId ?? ''),
      name: String(e.name ?? e.templateId ?? ''),
      level: e.level ?? 0,
      hp: e.hp ?? 0,
      maxHp: e.maxHp ?? 0,
      hostile: !!e.hostile,
      dead: !!e.dead,
      lootable: !!e.lootable,
      questIds: e.questIds ?? [],
      availableQuests: [],
      completableQuests: [],
      aggroOnMe: e.aggroTargetId != null && e.aggroTargetId === p.id,
      x: e.pos.x,
      z: e.pos.z,
      dist: d,
      bearing: normAngle(angleTo(p.pos as any, e.pos as any) - (p.facing ?? 0)),
    };
    // Что реально доступно нам у этого NPC — спрашиваем у игры, а не гадаем:
    // квест может быть закрыт по классу/пререквизиту (q_hub_healing_numbers),
    // а может быть непроходимым в headless-мире (gather/farm/escort).
    if (e.kind === 'npc') {
      const q = this.npcQuestsFor(view.templateId, view.questIds);
      view.availableQuests = q.available;
      view.completableQuests = q.completable;
    }
    return view;
  }

  /** Слой карты: статические пины NPC из контент-данных игры (NPCS[*].pos/questIds).
   *  Это не наблюдение за живыми сущностями, а знание карты и журнала квестов,
   *  доступное клиенту: где стоит квестодатель и кто принимает наш квест. */
  private buildMapPins(px: number, pz: number): MapPin[] {
    const pins: MapPin[] = [];
    for (const pin of npcPins()) {
      const q = this.npcQuestsFor(pin.templateId, pin.questIds);
      if (q.completable.length === 0) continue;
      pins.push({
        templateId: pin.templateId,
        name: pin.name,
        x: pin.x,
        z: pin.z,
        kind: 'giver',
        questId: q.completable[0],
        dist: Math.hypot(pin.x - px, pin.z - pz),
      });
    }
    const log = this.raw.questLog as Map<string, { questId: string; state: string }>;
    for (const qp of log.values()) {
      if (qp.state !== 'active' && qp.state !== 'ready') continue;
      const def = (QUESTS as Record<string, QuestDef>)[qp.questId];
      const tid = def?.turnInNpcId ?? def?.giverNpcId;
      if (!tid) continue;
      const pin = PIN_BY_ID.get(tid);
      if (!pin) continue;
      pins.push({
        templateId: pin.templateId,
        name: pin.name,
        x: pin.x,
        z: pin.z,
        kind: 'turnin',
        questId: qp.questId,
        dist: Math.hypot(pin.x - px, pin.z - pz),
      });
    }
    return pins.sort((a, b) => a.dist - b.dist);
  }

  /** Состояние квеста глазами игры. Требует questStateApi: без неё — исключение,
   *  а не «доступен по умолчанию» (молчаливых допущений не держим). */
  questState(questId: string): string {
    if (this.capabilities.questStateApi === 'none') {
      throw new Error('мир не предоставляет состояние квестов (questStateApi=none)');
    }
    return String(this.raw.questState(questId));
  }

  /** Кэш доступности квестов по шаблону NPC: состояние меняется только при
   *  изменении журнала/уровня/числа сдач, а наблюдение вызывается часто. */
  private npcQuestCache = new Map<string, { available: string[]; completable: string[] }>();
  private npcQuestCacheToken = '';

  private refreshNpcQuestCache(): void {
    const log = this.raw.questLog as Map<string, unknown>;
    const token = `${this.raw.player.level}:${this.raw.counters.questsCompleted}:${log.size}`;
    if (token !== this.npcQuestCacheToken) {
      this.npcQuestCacheToken = token;
      this.npcQuestCache.clear();
    }
  }

  private npcQuestsFor(
    templateId: string,
    questIds: string[],
  ): { available: string[]; completable: string[] } {
    const hit = this.npcQuestCache.get(templateId);
    if (hit !== undefined) return hit;
    const stateOf = (qid: string) => String(this.raw.questState(qid));
    const useful = predictedUsefulAccept(templateId, questIds, stateOf);
    const out = {
      available: questIds.filter((qid) => stateOf(qid) === 'available'),
      completable: useful ? [useful] : [],
    };
    this.npcQuestCache.set(templateId, out);
    return out;
  }

  /** Квесты из журнала игрока + доступные у видимых NPC. */
  private questViews(npcsInView: EntityView[]): QuestView[] {
    const out: QuestView[] = [];
    const seen = new Set<string>();
    const log = this.raw.questLog as Map<string, { questId: string; state: string; counts: number[] }>;
    for (const qp of log.values()) {
      seen.add(qp.questId);
      out.push(this.questView(qp.questId, qp.state, qp.counts ?? []));
    }
    for (const npc of npcsInView) {
      for (const qid of npc.questIds) {
        if (seen.has(qid)) continue;
        seen.add(qid);
        const st = String(this.raw.questState(qid));
        if (st === 'available') out.push(this.questView(qid, st, []));
      }
    }
    return out;
  }

  private questView(qid: string, rawState: string, counts: number[]): QuestView {
    const def = (QUESTS as Record<string, QuestDef>)[qid];
    const state: QuestStateName =
      rawState === 'available' || rawState === 'active' || rawState === 'ready' || rawState === 'done'
        ? rawState
        : 'other';
    const objectives: ObjectiveView[] = (def?.objectives ?? []).map((o, i) => ({
      type: o.type,
      targetMobId: o.targetMobId,
      targetNpcId: o.targetNpcId,
      itemId: o.itemId,
      targetObjectItemId: o.targetObjectItemId,
      required: o.count,
      have: Math.min(counts[i] ?? 0, o.count),
      label: o.label,
    }));
    return {
      id: qid,
      name: def?.name ?? qid,
      state,
      objectives,
      progress: objectives.reduce((s, o) => s + o.have, 0),
      required: objectives.reduce((s, o) => s + o.required, 0),
      giverNpcId: def?.giverNpcId,
      turnInNpcId: def?.turnInNpcId,
    };
  }
}

export { activeQuest, readyQuest };
