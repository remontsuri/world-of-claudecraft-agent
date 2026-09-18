/**
 * executor.ts — единственная точка исполнения навыков (порт core/SkillExecutor.java).
 *
 * Главное отличие от Java-линии: там исполнитель звал серверные композиты моста
 * (`navigate`, `step(idx, ctx)`), здесь в мире есть только канонические 61 действие
 * upstream, поэтому композиты собраны из примитивов самим исполнителем.
 * Никаких зашитых координат: цели берутся из наблюдения и из памяти.
 *
 * Ограничение, заявленное честно: в каноническом action space нет выбора цели —
 * только `target_nearest`. Поэтому farm бьёт ближайшего врага, а не «того самого»
 * моба квеста; нужный тип моба влияет на то, КУДА мы идём (navigate), а не кого бьём.
 */
import { angleTo, normAngle } from '../../game/src/sim/types';
import { allCamps, campsFor, classAbilities, mobLevelRange, mobsDropping } from '../facts';
import { PARAMS } from '../policy/params';
import { WorldMemory, type Coord } from '../memory/memory';
import type { World } from '../world/world';
import { canFightMob, questPriority } from '../world/quest_policy';
import {
  activeQuest,
  aggressors,
  availableGiverInRange,
  type EntityView,
  hasMobInMeleeRange,
  hasReadyQuest,
  hpFraction,
  lootInRange,
  type MapPin,
  nearestAvailableGiver,
  nearestGiver,
  nearestObject,
  nearestTurnInNpc,
  questGiverInRange,
  readyQuest,
  threateningNear,
  turnInNpcInRange,
  type WorldModel,
  type QuestView,
} from '../world/types';
import { canonical, isSupported } from './canon';

const NAV_MAX_STEPS = PARAMS.navMaxSteps; // бюджет подхода к цели (в действиях мира)
const APPROACH_STOP = PARAMS.approachStop; // ярды: ближе MELEE_RANGE=5, чтобы удар наверняка доставал
const TURN_TOLERANCE = PARAMS.turnTolerance; // рад (~20°): цель в секторе, можно бить
const FACE_MAX_ACTIONS = PARAMS.faceMaxActions; // сколько действий на доворот (поворот = 45° за действие)
const COMBAT_MAX_ACTIONS = PARAMS.combatMaxActions; // 64 × 0.25 с = 16 с мира: замах ~2 с, значит 7-8 ударов —
// волк зоны 1 (40-54 HP) уровнем 1 за 2-3 удара не умирает, прежние 6 с не убивали никого
const APPROACH_RETRY = PARAMS.approachRetry; // бюджет повторного подхода в бою
const UNKILLABLE_HP_FACTOR = PARAMS.unkillableHpFactor; // цель с HP больше 5× наших за навык не убивается — не тратим бюджет
const LOW_HP_ABORT = PARAMS.lowHpAbort; // ниже — выходим из боя: мобы быстрее игрока (RUN_SPEED=7, волк 8),
// догнавший нас бой заканчивается смертью, поэтому порог выше «классических» 30%
const LEVEL_DELTA_MAX = PARAMS.levelDeltaMax; // не бьём мобов выше нашего уровня более чем на 1
const ENGAGE_RADIUS = PARAMS.engageRadius; // ярдов: в этом радиусе ищем «друзей» цели перед боем
const ENGAGE_MAX_NEIGHBOURS = PARAMS.engageMaxNeighbours; // цель + 1 сосед — максимум для честного боя 1×1
const HEAL_MAX_ACTIONS = PARAMS.healMaxActions; // 40 × 0.25 с = 10 с мира на отдых/реген
const HEAL_TARGET = PARAMS.healTarget; // до какой доли HP отдыхаем
const HEAL_THREAT_DIST = PARAMS.healThreatDist; // ярдов: ближе — не отдыхаем, а отходим
const CROWD_ABORT_HP = PARAMS.crowdAbortHp; // если в бой втянулась стая, выходим уже при 75% HP
const CROWD_LIMIT_FARM = PARAMS.crowdLimitFarm; // за нами уже бежит двое — новый бой не начинаем
const FLEE_MAX_ACTIONS = PARAMS.fleeMaxActions; // 6 с мира на отход
const FLEE_TURN_MAX = PARAMS.fleeTurnMax; // действий на разворот от угрозы
const FLEE_SAFE_DIST = PARAMS.fleeSafeDist; // ярдов: дальше этой дистанции отрыв считаем успешным
const HAVEN_DIST = PARAMS.havenDist; // ярдов: ближайший NPC в этом радиусе считаем убежищем (город)
const UNSTUCK_MIN_MOVE = PARAMS.unstuckMinMove; // ярдов: меньше — значит уперлись в геометрию, надо довернуть
const SEARCH_ACTIONS = PARAMS.searchActions; // действий на поиск на месте (3 с мира ≈ 21 ярд хода)
const RESPAWN_WAIT_ACTIONS = PARAMS.respawnWaitActions; // 80 × 0.25 с = 20 с мира: с запасом на respawnSeconds=15

export interface ApproachResult {
  arrived: boolean;
  actions: number;
  dist: number;
}

/** Предметы целей collect, которых ещё не хватает (для проверки лута по факту). */
export function collectItemIds(q: QuestView | null): string[] {
  if (!q) return [];
  return q.objectives
    .filter((o) => o.type === 'collect' && o.have < o.required && o.itemId)
    .map((o) => o.itemId as string);
}

/** Доля HP сущности: у стенда hp/maxHp, за бриджем obs отдаёт долю напрямую
 *  (hp=доля, maxHp=1) — формула одна и та же, транспорт не важен. */
export function entityHpFraction(e: EntityView | null): number {
  if (!e) return 1;
  return e.maxHp > 0 ? e.hp / e.maxHp : 0;
}

export class SkillExecutor {
  private explorePhase = 0;
  private stuckCount = 0;
  private lastPos: Coord | null = null;

  constructor(
    private readonly world: World,
    private readonly memory: WorldMemory,
    private readonly ranges: { meleeRange: number; interactRange: number },
  ) {}

  execute(skill: string, w: WorldModel): string {
    // Инвариант: любое решение двигает мир хотя бы на одно каноническое действие.
    // Иначе мёртвый агент навсегда замирает до респавна (так было: heal возвращался
    // без действия, мир стоял на step=985, респавн 15 с не наступал).
    if (!skill || skill === 'noop') {
      this.world.stepAction('noop');
      return 'NOOP';
    }
    const name = canonical(skill); // не из канона -> исключение, не молчаливый no-op
    if (!isSupported(name)) return `UNSUPPORTED_FAILED:${name}`;
    try {
      switch (name) {
        case 'farm':
          return this.farm(w);
        case 'loot':
          return this.loot(w);
        case 'accept_quest':
          return this.acceptQuest(w);
        case 'turn_in_quest':
          return this.turnIn(w);
        case 'heal':
          return this.heal(w);
        case 'navigate':
          return this.navigate(w);
        case 'return_to_giver':
          return this.turnIn(w); // в headless-мире возврат и сдача — один поход к NPC
        case 'flee':
          return this.flee();
        case 'explore':
          return this.explore(w);
        case 'cast_frostbolt':
          return this.cast(w, 'frostbolt');
        case 'cast_fireball':
          return this.cast(w, 'fireball');
        default:
          return `UNKNOWN_SKILL:${name}`;
      }
    } catch (e) {
      return `ERROR:${(e as Error).message}`;
    }
  }

  // ------------------------------------------------------------------ навыки

  /** farm: выбрать цель, подойти, довернуться, бить до смерти/конца бюджета. */
  private farm(w: WorldModel): string {
    // Отказ от боя ДО начала — это тактика, а не поломка навыка: с суффиксом
    // _FAILED арбитраж ставил farm на перерыв, и агент замирал рядом с мобом.
    const frac0 = hpFraction(w);
    const chased0 = aggressors(w).length;
    if (frac0 < LOW_HP_ABORT) {
      this.world.stepAction('back');
      return `NOT_NOW:hp=${Math.round(frac0 * 100)}`;
    }
    if (chased0 >= CROWD_LIMIT_FARM) {
      this.world.stepAction('back');
      return `NOT_NOW:crowd=${chased0}`;
    }
    const q = activeQuest(w);
    const templates = this.questMobTemplates(q);
    // Цель квеста без убийств и без сбора (например «нанеси 10 ударов по учебному
    // манекену»): тогда бьём ближайшего врага, даже если он не убиваем.
    const objectiveIsNotKill = !!q && templates.size === 0 && q.objectives.length > 0;
    const mob = this.pickTarget(w, templates, objectiveIsNotKill);
    if (!mob) {
      this.world.stepAction('turn_left'); // оглядеться: решение обязано двигать мир
      return 'NO_TARGET';
    }
    // Бой 1×1: если у цели есть соседи в ENGAGE_RADIUS, нас задавят стаей —
    // в прогоне 400 решений это дало 232 смерти при 11 убийствах.
    if (!objectiveIsNotKill) {
      const neighbours = threateningNear(w, ENGAGE_RADIUS).filter((m) => m.id !== mob.id).length;
      if (neighbours > ENGAGE_MAX_NEIGHBOURS) {
        this.world.stepAction('back');
        this.world.stepAction('back'); // отходим, не ввязываясь
        // НЕ «_FAILED»: это осознанный тактический отказ, а не ошибка навыка.
        // С суффиксом _FAILED арбитраж ставил farm на перерыв 60 решений, и агент
        // замирал рядом с мобом (123 принудительных noop в прогоне seed 42).
        return `OUTNUMBERED:${this.targetLabel(mob)}:${neighbours}`;
      }
    }
    // Память по виду моба имеет смысл, только если мир вид отдаёт: за бриджем
    // templateId пустой, и запись «пятна» с пустым ключом замусорила бы память.
    if (mob.templateId) this.memory.saveMobSpot(mob.templateId, { x: mob.x, z: mob.z });
    if (q) this.memory.saveQuestMobCoord(q.id, { x: mob.x, z: mob.z });

    if (mob.dist > APPROACH_STOP) {
      const r = this.approach({ x: mob.x, z: mob.z }, APPROACH_STOP, NAV_MAX_STEPS);
      if (!r.arrived) return `WALK:mob:${this.targetLabel(mob)}:${r.dist.toFixed(1)}`;
    }
    const faced = this.faceTarget(mob);

    const killsBefore = this.world.counters.kills;
    const dmgBefore = this.world.counters.damageDealt;
    const qpBefore = this.world.counters.questProgress;
    // Доля HP цели — наблюдаемый факт в обоих транспортах (у стенда hp/maxHp,
    // за бриджем obs отдаёт долю напрямую). Понадобится, если мир не отдаёт
    // накопленный урон (damageCounters=false): иначе бой, который явно прошёл
    // не холостым, выглядел бы как FARM_FAILED и навык вставал на перерыв.
    const fracBefore = entityHpFraction(mob);
    let fracMin = fracBefore;
    // Выбор цели. Стенд даёт только `target_nearest` (в src/world_api.ts игры это
    // dispatch-only RL-токен: по проводу он не ходит), поэтому на стенде мы бьём
    // ближайшего врага, а не «того самого» моба квеста. Живой мир даёт wire-команды
    // `target`/`tab` — тогда цель выбираем явно. Никакого молчаливого выбора:
    // ветка определяется объявленной возможностью мира.
    if (this.world.capabilities.targetSelection === 'free' && this.world.targetEntity) {
      this.world.targetEntity(mob.id);
    } else {
      this.world.stepAction('target_nearest');
    }
    this.world.stepAction('attack');
    let actions = 2 + faced;

    while (actions < COMBAT_MAX_ACTIONS && !this.world.ended) {
      const cur = this.world.observe();
      // Если к бою подтянулась стая (агрится на нас), выходим раньше: на низком
      // пороге HP нас добивают за один-два замаха.
      const crowd = aggressors(cur).length;
      const abortFrac = crowd > ENGAGE_MAX_NEIGHBOURS ? CROWD_ABORT_HP : LOW_HP_ABORT;
      if (hpFraction(cur) < abortFrac) break; // дальше решает арбитраж: flee/heal
      const t = cur.target;
      if (!t || t.dead) break;
      fracMin = Math.min(fracMin, entityHpFraction(t));
      if (t.dist > this.ranges.meleeRange) {
        const r = this.approach({ x: t.x, z: t.z }, APPROACH_STOP, APPROACH_RETRY);
        actions += r.actions;
        if (!r.arrived) break;
        continue;
      }
      if (Math.abs(t.bearing) > TURN_TOLERANCE) {
        this.world.stepAction(t.bearing > 0 ? 'turn_left' : 'turn_right');
        actions++;
        continue;
      }
      this.world.stepAction(this.bestAbility(cur, t.dist) ?? 'attack');
      actions++;
    }

    const after = this.world.counters;
    if (after.kills > killsBefore) return `FARM:${this.targetLabel(mob)}`;
    if (after.questProgress > qpBefore) return `FARM_OBJ:${q?.id ?? '?'}:${after.questProgress}`;
    if (this.world.capabilities.damageCounters && after.damageDealt > dmgBefore) {
      return `FARM_DMG:${this.targetLabel(mob)}`;
    }
    if (fracMin < fracBefore - 1e-6) {
      return `FARM_HP:${this.targetLabel(mob)}:${fracBefore.toFixed(2)}->${fracMin.toFixed(2)}`;
    }
    return 'FARM_FAILED';
  }

  /** Шаблоны мобов, которых надо бить ради квеста: прямые цели kill плюс
   *  источники лута для целей collect (таблицы лута игры, facts.mobsDropping). */
  private questMobTemplates(q: QuestView | null): Set<string> {
    const out = new Set<string>();
    if (!q) return out;
    for (const o of q.objectives) {
      if (o.type === 'kill' && o.targetMobId && o.have < o.required) out.add(o.targetMobId);
      else if (o.type === 'collect' && o.have < o.required) for (const t of mobsDropping(o.itemId)) out.add(t);
    }
    return out;
  }

  /** Имя цели для журнала: за бриджем вид сущности неизвестен (entityTemplates=false),
   *  и пустая строка в доказательствах выглядела бы как потеря данных. */
  private targetLabel(e: EntityView): string {
    return e.templateId || 'вид_неизвестен';
  }

  /** Выбор цели: сначала цель квеста, затем убиваемая, затем ближайшая.
   *  Не берём mob выше нашего уровня более чем на LEVEL_DELTA_MAX и заведомо
   *  неубиваемых (учебный манекен 999999 HP) — кроме квеста «бей манекен». */
  private pickTarget(
    w: WorldModel,
    questTemplates: ReadonlySet<string>,
    objectiveIsNotKill: boolean,
  ): EntityView | null {
    const cap = UNKILLABLE_HP_FACTOR * Math.max(1, w.player.maxHp);
    const levelOk = (x: EntityView) => x.level <= w.player.level + LEVEL_DELTA_MAX;
    const killable = (x: EntityView) => x.maxHp <= cap && levelOk(x);
    if (questTemplates.size > 0) {
      const m = w.nearby.find((x) => questTemplates.has(x.templateId) && (objectiveIsNotKill || killable(x)));
      if (m) return m;
    }
    if (!objectiveIsNotKill) {
      const ok = w.nearby.filter(killable);
      if (ok.length > 0) return ok[0];
      return null; // бить некого: пусть решает арбитраж (navigate/explore), а не бой насмерть
    }
    return w.nearby[0] ?? null;
  }

  /** Слот способности по имени: имена — из набора класса (facts.classAbilities),
   *  готовность — из наблюдения игры. Возвращает каноническое действие ability_N. */
  private abilityAction(name: string): string | null {
    const a = this.world.abilities().find((x) => x.id === name && x.ready);
    return a ? `ability_${a.slot + 1}` : null;
  }

  /** Довернуться на цель: автоатака бьёт только в секторе перед игроком. */
  private faceTarget(t: EntityView): number {
    let used = 0;
    let cur: EntityView | null = t;
    while (cur && Math.abs(cur.bearing) > TURN_TOLERANCE && used < FACE_MAX_ACTIONS && !this.world.ended) {
      this.world.stepAction(cur.bearing > 0 ? 'turn_left' : 'turn_right');
      used++;
      const w = this.world.observe();
      cur = w.target ?? w.nearby.find((n) => n.id === cur!.id) ?? null;
    }
    return used;
  }

  /** loot: обыскать ближайший труп. Успех меряем по фактам игры (медь, предметы
   *  через публичный Sim.countItem, прогресс квеста), а не по исчезновению трупа:
   *  труп остаётся, если на нём ещё что-то лежит, и «не исчез» ≠ «не облутали». */
  private loot(w: WorldModel): string {
    const corpse = lootInRange(w, this.ranges.interactRange) ?? w.corpses[0];
    if (!corpse) {
      this.world.stepAction('noop'); // решение обязано двигать мир
      return 'NO_CORPSE';
    }
    if (corpse.dist > this.ranges.interactRange) {
      const r = this.approach({ x: corpse.x, z: corpse.z }, this.ranges.interactRange * 0.8, 20);
      if (!r.arrived) return `WALK:corpse:${corpse.templateId}:${r.dist.toFixed(1)}`;
    }
    // Число предметов в сумках — привилегия стенда (Sim.countItem). Живой мир может
    // его не давать: тогда честно пишем «не проверено», а не «не удалось».
    const verified = this.world.capabilities.itemCountApi;
    const wanted = verified ? collectItemIds(activeQuest(w)) : [];
    const before = this.lootSnapshot(wanted);
    this.world.stepAction('interact');
    const after = this.lootSnapshot(wanted);
    if (after.copper > before.copper) return `LOOT:${corpse.templateId}:copper+${after.copper - before.copper}`;
    const got = wanted.filter((it) => (after.items[it] ?? 0) > (before.items[it] ?? 0));
    if (got.length > 0) return `LOOT:${corpse.templateId}:${got.join('+')}`;
    if (after.questProgress > before.questProgress) return `LOOT:${corpse.templateId}:quest`;
    const now = this.world.observe();
    if (!now.corpses.some((c) => c.id === corpse.id)) return `LOOT_EMPTY:${corpse.templateId}`;
    return verified ? 'LOOT_FAILED' : 'LOOT_UNVERIFIED';
  }

  private lootSnapshot(itemIds: readonly string[]): { copper: number; questProgress: number; items: Record<string, number> } {
    const items: Record<string, number> = {};
    for (const id of itemIds) items[id] = this.world.countItem(id);
    return { copper: this.world.copper, questProgress: this.world.counters.questProgress, items };
  }

  /** heal: лечебное заклинание, если класс его знает; у воина таких нет — тогда
   *  канонический отдых: снять автоатаку (stop), отойти от угрозы, поесть/попить
   *  (eat_drink) и ждать регена (noop). Именно «отойти и отдохнуть»: прежняя версия
   *  возвращала HEAL_IN_COMBAT_FAILED без движения, и агент стоял под стаей с 29% HP. */
  private heal(w: WorldModel): string {
    if (w.player.dead) {
      // Мёртвый не лечится: ждём воскрешения игры, двигая мир каноническим noop.
      let used = 0;
      while (used < RESPAWN_WAIT_ACTIONS && !this.world.ended && this.world.observe().player.dead) {
        this.world.stepAction('noop');
        used++;
      }
      return this.world.observe().player.dead ? `RESPAWN_WAIT:${used}` : `RESPAWNED:${used}`;
    }
    const hpBefore = w.player.hp;
    this.world.stepAction('stop');
    let used = 1;
    // Самохил класса (у воина furious_mending), если есть и готов: отдых без него
    // слишком медленный, пока вокруг respawn-зоны бродят мобы.
    const mend = this.abilityAction('furious_mending');
    if (mend) {
      this.world.stepAction(mend);
      used++;
    }
    while (used < HEAL_MAX_ACTIONS && !this.world.ended) {
      const cur = this.world.observe();
      if (hpFraction(cur) >= HEAL_TARGET) break;
      const threat = aggressors(cur, HEAL_THREAT_DIST)[0];
      if (threat) {
        // Под ударом не отдыхаем: разворачиваемся спиной и отходим.
        const err = normAngle(threat.bearing - Math.PI);
        this.world.stepAction(Math.abs(err) > TURN_TOLERANCE ? (err > 0 ? 'turn_left' : 'turn_right') : 'forward');
        used++;
        continue;
      }
      this.world.stepAction(used % 8 === 1 ? 'eat_drink' : 'noop');
      used++;
    }
    const gained = this.world.observe().player.hp - hpBefore;
    return gained > 0 ? `HEAL:${Math.round(gained)}` : 'HEAL_FAILED';
  }

  /** flee: снять автоатаку и уйти. Куда — в ближайший город (NPC), если он в
   *  HAVEN_DIST, иначе просто от угрозы. Игрок быстрее преследователя: у игры
   *  FLEE_MAX_SPEED = RUN_SPEED*0.65 (flee_speed.ts), поэтому прямой отход
   *  работает, если не упираться в геометрию — для этого есть доворот при застревании.
   *  Прежние варианты (3 шага назад / слепой бег) дали 232 смерти за 400 решений. */
  private flee(): string {
    const w0 = this.world.observe();
    if (w0.player.dead) {
      this.world.stepAction('noop'); // двигаем мир к воскрешению
      return 'FLEE_DEAD';
    }
    // Убежище — настоящий городской NPC (с квестами), а не spirit_healer у трупа:
    // к духу-целителю бежать бессмысленно, он сам появляется рядом с телом.
    const haven = w0.npcs.find((n) => n.questIds.length > 0 && n.dist <= HAVEN_DIST) ?? null;
    const threatId = w0.nearby[0]?.id ?? null;
    this.world.stepAction('stop');
    let used = 1;
    // Разворот: к убежищу — лицом (bearing -> 0), от угрозы — спиной (|bearing| -> π).
    const want = haven ? 0 : Math.PI;
    while (used < FLEE_TURN_MAX && !this.world.ended) {
      const cur = this.world.observe();
      const ref = haven ?? cur.nearby.find((m) => m.id === threatId) ?? cur.nearby[0];
      if (!ref) break;
      const err = normAngle(ref.bearing - want);
      if (Math.abs(err) <= TURN_TOLERANCE) break;
      this.world.stepAction(err > 0 ? 'turn_left' : 'turn_right');
      used++;
    }
    // Мобы в зоне быстрее игрока (данные игры: RUN_SPEED=7, forest_wolf 8,
    // wild_boar 7.5), поэтому пешком не оторваться — сначала замедляем
    // преследователя (hamstring) и прыгаем (heroic_leap), потом бежим.
    const threatNow = this.world.observe().nearby[0] ?? null;
    const slow = this.abilityAction('hamstring');
    if (slow && threatNow && threatNow.dist <= this.ranges.meleeRange * 1.5) {
      this.world.stepAction(slow);
      used++;
    }
    const leap = this.abilityAction('heroic_leap');
    if (leap && used < FLEE_MAX_ACTIONS) {
      this.world.stepAction(leap);
      used++;
    }
    // На бегу лечимся, чем умеем: у воина это furious_mending (имя — из набора класса).
    const mend = this.abilityAction('furious_mending');
    if (mend && used < FLEE_MAX_ACTIONS) {
      this.world.stepAction(mend);
      used++;
    }
    let prev: Coord = { x: w0.player.x, z: w0.player.z };
    let unstuck = 0;
    while (used < FLEE_MAX_ACTIONS && !this.world.ended) {
      const cur = this.world.observe();
      const t = aggressors(cur)[0] ?? cur.nearby[0];
      if (t && t.dist > FLEE_SAFE_DIST) break;
      if (!t && !haven) break;
      this.world.stepAction('forward');
      used++;
      const p = this.world.observe().player;
      const moved = Math.hypot(p.x - prev.x, p.z - prev.z);
      prev = { x: p.x, z: p.z };
      if (moved < UNSTUCK_MIN_MOVE) {
        // Упёрлись (здание/вода/склон): доворачиваем, чтобы обойти, а не толкать стену.
        this.world.stepAction(unstuck % 2 === 0 ? 'turn_left' : 'strafe_right');
        unstuck++;
        used++;
      }
    }
    const now = this.world.observe();
    const d = now.nearby[0]?.dist ?? Number.POSITIVE_INFINITY;
    const where = haven ? `haven:${haven.templateId}` : 'away';
    return d > FLEE_SAFE_DIST ? `FLEE:${where}:${Math.round(d)}` : `FLEE_SHORT:${where}:${Math.round(d)}`;
  }

  /** Провалы выдачи квеста по NPC: ACCEPT_FAILED → счётчик → вычёркивание. */
  private readonly acceptFails = new Map<string, number>();

  /** accept_quest: сначала дойти до NPC, только потом говорить (INTERACT_RANGE).
   *  Цель — NPC с ДОСТУПНЫМ квестом: закрытые по классу/пререквизиту не долбим. */
  private acceptQuest(w: WorldModel): string {
    const giver = availableGiverInRange(w, this.ranges.interactRange);
    if (!giver) {
      const target = this.giverTarget(w);
      if (!target) return 'NO_GIVER';
      const r = this.approach(target.coord, this.ranges.interactRange * 0.8, NAV_MAX_STEPS);
      if (!r.arrived) return `NAV_GIVER:${target.what}:${r.dist.toFixed(1)}`;
      // Дошли, а доступного квеста так и нет: NPC для нас бесполезен — запоминаем
      // и уходим, иначе агент вечно «прибывает» к закрытой двери (так и было:
      // 34 ARRIVED_GIVER у Drillmaster Hale, чей второй квест закрыт по классу).
      const now = this.world.observe();
      if (availableGiverInRange(now, this.ranges.interactRange)) return 'ARRIVED_GIVER';
      const closest = now.npcs.find((n) => n.dist <= this.ranges.interactRange * 1.5);
      if (closest) this.memory.markGiverExhausted(closest.templateId);
      return closest ? `GIVER_EXHAUSTED:${closest.templateId}` : 'NO_GIVER';
    }
    this.memory.rememberGiver(giver.templateId, { x: giver.x, z: giver.z });
    for (const qid of giver.questIds) this.memory.rememberGiver(qid, { x: giver.x, z: giver.z });

    const before = w.quests.filter((q) => q.state === 'active').length;
    this.world.stepAction('interact');
    const after = this.world.observe();
    const active = after.quests.filter((q) => q.state === 'active');
    if (active.length > before) {
      this.acceptFails.delete(giver.templateId);
      return `ACCEPT:${active[active.length - 1].id}`;
    }
    // Игра ничего не выдала. Причина по наблюдению недоступна: квест может быть
    // закрыт по классу/пререквизиту, а за бриджем состояние 'available' вообще
    // неразличимо с 'none'. Поэтому учимся на провалах: после giverFailExhaust
    // подряд неудач у одного NPC вычёркиваем его (иначе агент вечно долбит
    // закрытую дверь — ровно так было с Drillmaster Hale в стенде: 34 прибытия).
    const fails = (this.acceptFails.get(giver.templateId) ?? 0) + 1;
    this.acceptFails.set(giver.templateId, fails);
    if (fails >= PARAMS.giverFailExhaust) {
      this.memory.markGiverExhausted(giver.templateId);
      return `GIVER_EXHAUSTED:${giver.templateId}:accept_failed×${fails}`;
    }
    return `ACCEPT_FAILED:${giver.templateId}:${fails}/${PARAMS.giverFailExhaust}`;
  }

  /** turn_in_quest: дойти до принимающего NPC и сдать готовый квест. */
  private turnIn(w: WorldModel): string {
    const q = readyQuest(w);
    if (!q) return 'NO_READY_QUEST';
    const npc = turnInNpcInRange(w, q, this.ranges.interactRange) ?? nearestTurnInNpc(w, q);
    const pin = w.mapPins.find((p) => p.kind === 'turnin' && p.questId === q.id);
    const coord: Coord | null = npc
      ? { x: npc.x, z: npc.z }
      : pin
        ? { x: pin.x, z: pin.z }
        : (this.memory.giverLocation(q.id) ?? this.memory.giverLocation(q.turnInNpcId ?? q.giverNpcId ?? ''));
    if (!coord) return 'NO_GIVER_COORD';
    if (npc) this.memory.rememberGiver(q.id, coord);

    const dist = Math.hypot(coord.x - w.player.x, coord.z - w.player.z);
    if (dist > this.ranges.interactRange) {
      const r = this.approach(coord, this.ranges.interactRange * 0.8, NAV_MAX_STEPS);
      if (!r.arrived) return `RETURN_WALK:${q.id}:${r.dist.toFixed(1)}`;
    }
    const before = this.world.counters.questsCompleted;
    this.world.stepAction('interact');
    const after = this.world.counters.questsCompleted;
    return after > before ? `TURN_IN:${q.id}` : 'TURN_IN_FAILED';
  }

  /** navigate: к принимающему NPC (готовый квест), к цели активного квеста,
   *  иначе к ближайшему NPC с доступным квестом, иначе explore. */
  private navigate(w: WorldModel): string {
    const rq = readyQuest(w);
    const q = activeQuest(w);
    const questTemplates = this.questMobTemplates(q);
    let target: Coord | null = null;
    let what = 'unknown';
    if (rq) {
      const npc = nearestTurnInNpc(w, rq);
      const pin = w.mapPins.find((p) => p.kind === 'turnin' && p.questId === rq.id);
      target = npc ? { x: npc.x, z: npc.z } : pin ? { x: pin.x, z: pin.z } : this.memory.giverLocation(rq.id);
      what = `turnin:${rq.id}`;
    } else if (q) {
      const fightable = new Set([...questTemplates].filter((t) => this.canFight(t, w.player.level)));
      const live = fightable.size > 0 ? w.nearby.find((m) => fightable.has(m.templateId)) : undefined;
      if (live) {
        target = { x: live.x, z: live.z };
        what = `mob:${q.id}`;
        this.memory.saveQuestMobCoord(q.id, target);
      } else {
        // Цель interact: объект мира (учебный манекен, хижина, ящик) — идём и жмём interact.
        const objId = q.objectives.find((o) => o.type === 'interact' && o.have < o.required)?.targetObjectItemId;
        const obj = objId ? nearestObject(w, objId) : null;
        if (obj && obj.dist <= this.ranges.interactRange) {
          const before = this.world.counters.questProgress;
          this.world.stepAction('interact');
          const progressed = this.world.counters.questProgress > before;
          return progressed
            ? `INTERACT_OBJ:${q.id}:${obj.templateId}`
            : `INTERACT_OBJ_NO_PROGRESS:${obj.templateId}`;
        }
        if (obj) {
          target = { x: obj.x, z: obj.z };
          what = `obj:${q.id}:${obj.templateId}`;
        } else if (fightable.size === 0 && questTemplates.size > 0) {
          // Цель квеста нам не по уровню (q_greyjaw: Old Greyjaw 4 уровня при наших 2).
          // Идти туда — серия смертей, а не прогресс: мобы быстрее игрока, уйти
          // пешком нельзя. Поэтому качаемся на доступных мобах рядом.
          const visible = w.nearby.find(
            (m) => this.canFight(m.templateId, w.player.level) && m.maxHp <= UNKILLABLE_HP_FACTOR * Math.max(1, w.player.maxHp),
          );
          const camp = this.nearestFightableCamp(w.player);
          target = visible ? { x: visible.x, z: visible.z } : camp?.coord ?? null;
          what = visible ? `grind:${visible.templateId}` : camp ? `grind-camp:${camp.mobId}` : `nogrind:${q.id}`;
        } else {
          target =
            this.memory.questMobCoord(q.id) ??
            this.firstMobSpot(fightable) ??
            this.nearestCamp(fightable, w.player);
          what = `mob-mem:${q.id}`;
        }
      }
      if (!target && questTemplates.size === 0 && q.turnInNpcId) {
        const npc = w.npcs.find((n) => n.templateId === q.turnInNpcId);
        target = npc ? { x: npc.x, z: npc.z } : this.memory.giverLocation(q.id);
        what = `giver:${q.id}`;
      }
      if (!target) what = `noidea:${q.id}`;
    }
    if (!target) {
      const g = this.bestGiver(w);
      if (g) {
        target = g.coord;
        what = `giver:${g.what}`;
      }
    }
    if (!target) return this.explore(w);
    const r = this.approach(target, APPROACH_STOP, NAV_MAX_STEPS);
    if (!r.arrived) return `WALK:${what}:${r.dist.toFixed(1)}`;
    // Пришли, а цели нет: память устарела. Снимаем её и ищем дальше, иначе
    // агент бесконечно «прибывает» в одну точку (ровно та петля, что была
    // в Java-линии из-за зацикливания на уже обысканном трупе).
    const now = this.world.observe();
    const fromMobMemory =
      what.startsWith('mob-mem') || what.startsWith('mob:') || what.startsWith('grind');
    const objectiveMobVisible = what.startsWith('grind')
      ? now.nearby.some(
          (m) =>
            this.canFight(m.templateId, now.player.level) &&
            m.maxHp <= UNKILLABLE_HP_FACTOR * Math.max(1, now.player.maxHp),
        )
      : !!q && questTemplates.size > 0 && now.nearby.some((m) => questTemplates.has(m.templateId));
    // Проверка устаревшей памяти — только для целей-мобов: если мы пришли к NPC,
    // это не «устарело», это FIND_GIVER/TURN_IN, и исследовать там нечего.
    // Но стоять у NPC с НЕГОТОВЫМ квестом — тупик (так агент 100 решений подряд
    // возвращал ARRIVED:giver:q_greyjaw): уходим искать цель квеста.
    const atGiverWithoutReadyQuest =
      (what.startsWith('giver:') || what.startsWith('noidea:')) && !hasReadyQuest(now);
    if ((fromMobMemory && !objectiveMobVisible && !hasReadyQuest(now)) || atGiverWithoutReadyQuest) {
      if (q && what.startsWith('mob-mem')) this.memory.forgetQuestMob(q.id);
      // Ищем на месте несколькими действиями: одношаговый explore порождал петлю
      // «пришёл — ушёл — пришёл» (221 решение впустую в прогоне seed 42).
      return `STALE:${what}:${this.explore(now, SEARCH_ACTIONS)}`;
    }
    // Бой после прибытия НЕ запускаем отсюда: navigate обязан отвечать за своё
    // «прибыл», а не за результат чужого навыка (обёртка ARRIVED_FIGHT:...:FARM_FAILED
    // ставила navigate на перерыв и агент терял ещё и навигацию). Дальше дерётся
    // арбитраж: farm в приоритете, если доступный моб в пределах FARM_TRIGGER_DIST.
    // Мир при этом обязан двигаться: на месте оглядываемся (канонический turn_left).
    this.world.stepAction('turn_left');
    return `ARRIVED:${what}:${r.dist.toFixed(1)}`;
  }

  /** explore: детерминированная спираль (без Math.random — мир обязан replay-иться). */
  private explore(w: WorldModel, times = 1): string {
    const sawGiver = nearestGiver(w) !== null;
    let act = 'forward';
    for (let i = 0; i < times && !this.world.ended; i++) {
      const leg = 8 + Math.floor(this.explorePhase / 4) * 4;
      const inTurn = this.explorePhase % (leg + 2) >= leg;
      this.explorePhase++;
      act = inTurn ? 'turn_right' : 'forward';
      this.world.stepAction(act);
      const cur = this.world.observe();
      this.memory.markVisited(cur.player.x, cur.player.z);
    }
    const after = this.world.observe();
    const found = !sawGiver && nearestGiver(after) !== null;
    return found ? 'EXPLORE_ARRIVED' : `EXPLORE:${act}${times > 1 ? `x${times}` : ''}`;
  }

  /** cast_*: способность по имени из набора класса (слот = порядок изучения). */
  private cast(w: WorldModel, spellId: string): string {
    const abilities = classAbilities(w.player.playerClass);
    const slot = abilities.indexOf(spellId);
    if (slot < 0) return `UNSUPPORTED_FAILED:${spellId}`;
    const view = this.world.abilities()[slot];
    if (!view || !view.ready) return `CAST_NOT_READY_FAILED:${spellId}`;
    this.world.stepAction(`ability_${slot + 1}`);
    return `CAST:${spellId}`;
  }

  // ----------------------------------------------------------------- утилиты

  /** Способность для удара: первая готовая по порядку слотов.
   *  `charge` — сближение, вне ближнего боя; в упор его тратить не нужно. */
  private bestAbility(w: WorldModel, targetDist: number): string | null {
    const ready = this.world.abilities().filter((a) => a.ready && a.id !== `slot_${a.slot + 1}`);
    const chosen =
      ready.find((a) => (a.id === 'charge' ? targetDist > this.ranges.meleeRange : true)) ?? null;
    return chosen ? `ability_${chosen.slot + 1}` : null;
  }

  private giverTarget(w: WorldModel): { coord: Coord; what: string } | null {
    const g = this.bestGiver(w);
    if (g) return g;
    const q = activeQuest(w) ?? readyQuest(w);
    if (q) {
      const m = this.memory.giverLocation(q.id) ?? this.memory.giverLocation(q.giverNpcId ?? '');
      if (m) return { coord: m, what: `mem:${q.id}` };
    }
    for (const [key, coord] of this.memory.questGivers) return { coord, what: `mem:${key}` };
    return null;
  }

  /** По силам ли нам этот моб на нашем уровне (данные игры: minLevel/maxLevel).
   *  Old Greyjaw — 4 уровень, 110 HP, скорость 8.5 при RUN_SPEED игрока 7: идти
   *  к нему на 2-м уровне значит умереть, а не выполнить квест. */
  private canFight(templateId: string, playerLevel: number): boolean {
    return canFightMob(templateId, playerLevel);
  }

  /** Ближайший лагерь мобов, которых мы можем бить на своём уровне (цель прокачки). */
  private nearestFightableCamp(p: { x: number; z: number; level: number }): { coord: Coord; mobId: string } | null {
    let best: { coord: Coord; mobId: string } | null = null;
    let bestD = Number.POSITIVE_INFINITY;
    for (const c of allCamps()) {
      if (!this.canFight(c.mobId, p.level)) continue;
      const d = Math.hypot(c.x - p.x, c.z - p.z);
      if (d < bestD) {
        bestD = d;
        best = { coord: { x: c.x, z: c.z }, mobId: c.mobId };
      }
    }
    return best;
  }

  /** Куда идти за мобом квеста, если мы его ни разу не видели: центр ближайшего
   *  лагеря этого моба из данных игры (CAMPS). Это знание карты/текста квеста
   *  («Old Greyjaw бродит в глухих лесах севернее волчьих троп»), а не глобальное
   *  зрение: сами мобы по-прежнему видны только в VIEW_RADIUS. */
  private nearestCamp(templates: ReadonlySet<string>, p: { x: number; z: number }): Coord | null {
    let best: Coord | null = null;
    let bestD = Number.POSITIVE_INFINITY;
    for (const t of templates) {
      for (const c of campsFor(t)) {
        const d = Math.hypot(c.x - p.x, c.z - p.z);
        if (d < bestD) {
          bestD = d;
          best = { x: c.x, z: c.z };
        }
      }
    }
    return best;
  }

  /** Запасная цель по памяти: где мы видели моба нужного шаблона. */
  private firstMobSpot(templates: ReadonlySet<string>): Coord | null {
    for (const t of templates) {
      const spot = this.memory.mobSpot(t);
      if (spot) return spot;
    }
    return null;
  }

  /** Куда идти за квестом: сначала живой NPC в радиусе наблюдения, затем точка
   *  карты из контент-данных игры. Живой мир устроен так же: клиент знает карту и
   *  журнал квестов, но сущности получает только в радиусе интереса
   *  (PLAYER_INTEREST_DROP_RADIUS=100, headless env — 80). Порядок — по приоритету
   *  квеста, затем по дистанции; исключены NPC, признанные бесполезными. */
  private bestGiver(w: WorldModel): { coord: Coord; what: string } | null {
    const live = w.npcs.filter(
      (n) => n.completableQuests.length > 0 && !this.memory.isGiverExhausted(n.templateId),
    );
    if (live.length > 0) {
      let best = live[0];
      for (const n of live) if (this.giverScore(n) < this.giverScore(best)) best = n;
      return { coord: { x: best.x, z: best.z }, what: best.templateId };
    }
    // Порядок выбора пина зависит от того, что мир вообще показывает:
    //  - стенд (questStateApi='full'): доступность квеста известна, поэтому сначала
    //    приоритет типа цели и только потом дистанция;
    //  - мир за бриджем ('observed'): доступность НЕ видна (ноль в obs неразличим
    //    между available и none), и приоритет по типу цели уводил агента мимо
    //    ближайшего NPC к дальнему «kill-квесту», который мог оказаться закрытым.
    //    Поэтому идём к ближайшему пину и проверяем interact'ом: ошибиться стоя
    //    дешевле, чем ошибиться пройдя 60 ярдов.
    const byPriorityThenDist = (p: MapPin) => questPriority(p.questId) * 100000 + p.dist;
    const key = this.world.capabilities.questStateApi === 'full' ? byPriorityThenDist : (p: MapPin) => p.dist;
    const pin = w.mapPins
      .filter((p) => p.kind === 'giver' && !this.memory.isGiverExhausted(p.templateId))
      .sort((a, b) => key(a) - key(b))[0];
    return pin ? { coord: { x: pin.x, z: pin.z }, what: `pin:${pin.templateId}` } : null;
  }

  private giverScore(n: EntityView): number {
    return questPriority(n.completableQuests[0]) * 100000 + n.dist;
  }

  /** Идти к точке: доворот на цель (turn_*), затем forward. Один вызов = одно действие мира. */
  private approach(target: Coord, stopDist: number, maxActions: number): ApproachResult {
    // Состояние застревания живёт ровно один подход: иначе бой без движения
    // заряжал счётчик и следующий подход начинался с принудительных доворотов.
    this.lastPos = null;
    this.stuckCount = 0;
    let actions = 0;
    let w = this.world.observe();
    let dist = Math.hypot(target.x - w.player.x, target.z - w.player.z);
    while (actions < maxActions && dist > stopDist && !this.world.ended) {
      const bearing = normAngle(
        angleTo({ x: w.player.x, z: w.player.z } as any, { x: target.x, z: target.z } as any) -
          w.player.facing,
      );
      let act = Math.abs(bearing) > TURN_TOLERANCE ? (bearing > 0 ? 'turn_left' : 'turn_right') : 'forward';
      // застревание: три шага без движения -> принудительный доворот (в мире есть
      // и свой unstuck, но агент обязан замечать, что не движется)
      if (this.lastPos && Math.hypot(w.player.x - this.lastPos.x, w.player.z - this.lastPos.z) < 0.2) {
        if (++this.stuckCount >= 3) {
          act = 'turn_right';
          this.stuckCount = 0;
        }
      } else {
        this.stuckCount = 0;
      }
      this.lastPos = { x: w.player.x, z: w.player.z };
      this.world.stepAction(act);
      actions++;
      w = this.world.observe();
      this.memory.markVisited(w.player.x, w.player.z);
      dist = Math.hypot(target.x - w.player.x, target.z - w.player.z);
    }
    return { arrived: dist <= stopDist, actions, dist };
  }
}

export { canonical, isSupported };
export type { EntityView };
