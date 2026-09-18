/**
 * arbitration.ts — порт arbitration/ArbitrationLayer.java.
 *
 * Константы перенесены 1:1 (LOW_HP 0.30, CRIT_HP 0.15, LOOP_THRESHOLD 6,
 * FAIL_LIMIT 3, FAIL_COOLDOWN 60) — это наши пороги, объявленные до измерения.
 * Отличия от Java-версии, оба осознанные:
 *   1) в списках фаз — канонические имена (turn_in_quest вместо алиаса turn_in,
 *      sell_junk вместо sell): алиасов в решении быть не должно, только в каноне;
 *   2) добавлен явный запрет навыков (disable) — для headless-мира, где части
 *      канона просто не существует. Запрет заявляется до прогона и печатается.
 */
import {
  aggressors,
  availableGiverInRange,
  type EntityView,
  hasActiveQuest,
  hasMobInMeleeRange,
  hasReadyQuest,
  hpFraction,
  lootInRange,
  nearestAvailableGiver,
  nearestGiver,
  nearestPin,
  nearestTurnInNpc,
  questGiverInRange,
  readyQuest,
  threateningNear,
  turnInNpcInRange,
  type WorldModel,
} from '../world/types';
import type { GoalFSM, QuestPhase } from './fsm';
import { canFightMob, canFightObservedLevel } from '../world/quest_policy';
import type { WorldCapabilities } from '../world/world';
import { PARAMS } from '../policy/params';
import type { WorldMemory } from '../memory/memory';

const PHASE_ALLOWED: Record<string, string[]> = {
  NO_QUEST: ['accept_quest', 'farm', 'loot', 'explore', 'navigate', 'gather'],
  FIND_GIVER: ['accept_quest', 'navigate', 'explore'],
  ACCEPT: ['accept_quest'],
  DO_OBJECTIVE: [
    'farm',
    'loot',
    'navigate',
    'gather',
    'heal',
    'sell_junk',
    'buy',
    'equip',
    'cast_frostbolt',
    'cast_fireball',
    'explore',
  ],
  RETURN_TO_GIVER: ['return_to_giver', 'navigate', 'flee'],
  TURN_IN: ['turn_in_quest', 'flee'],
  SELL_REPAIR: ['sell_junk', 'buy'],
  HEAL: ['heal'],
};

export const LOW_HP = PARAMS.lowHp;
export const CRIT_HP = PARAMS.critHp;
export const LOOP_THRESHOLD = PARAMS.loopThreshold;
export const FAIL_LIMIT = PARAMS.failLimit;
export const FAIL_COOLDOWN = PARAMS.failCooldown; // решений: 60 (как в Java-линии) парализовывало навык
// на четверть прогона — при 400 решениях это 15% времени простоя рядом с целью
/** Порог объявлен до измерения: лечить полного HP — тратить решение впустую. */
export const HEAL_BELOW = PARAMS.healBelow;
// Пороги «толпы» (дополнение к Java-порту, причина — 17 смертей в прогоне 400).
export const CROWD_RADIUS = PARAMS.crowdRadius; // ярдов: кого считаем «рядом» (радиус аггро зверя в зоне 1)
export const CROWD_LIMIT = PARAMS.crowdLimit; // сколько врагов рядом уже толпа
export const FLEE_TRIGGER_DIST = PARAMS.fleeTriggerDist; // ярдов: дальше угрозы уже нет смысла бежать — надо лечиться
export const FARM_TRIGGER_DIST = PARAMS.farmTriggerDist; // ярдов: доступного по уровню моба на этой дистанции уже бьём
export const UNKILLABLE_HP_FACTOR = PARAMS.unkillableHpFactor; // цель с HP больше 5× наших не убивается (учебный манекен)

export class ArbitrationLayer {
  private readonly failures = new Map<string, number>();
  private readonly cooldown = new Map<string, number>();
  private readonly disabled = new Set<string>();
  private lastAction = '';
  private repeatCount = 0;

  constructor(
    private readonly fsm: GoalFSM,
    private readonly memory: WorldMemory,
    private readonly ranges: { meleeRange: number; interactRange: number },
    /** Что мир вообще показывает: от этого зависит, по каким данным решать
     *  (вид сущности и абсолютное HP есть только у стенда — см. fightable()). */
    private readonly caps: WorldCapabilities,
  ) {}

  /** Явно запретить навык (например, невыполнимый в этом мире). */
  disable(...skills: string[]): void {
    for (const s of skills) this.disabled.add(s);
  }

  get disabledSkills(): string[] {
    return [...this.disabled].sort();
  }

  get onCooldown(): string[] {
    return [...this.cooldown.keys()].sort();
  }

  /** Результат исполнения: серия провалов -> временный запрет навыка. */
  reportResult(skill: string | null, ok: boolean): void {
    if (!skill) return;
    if (ok) {
      this.failures.delete(skill);
      this.cooldown.delete(skill);
      return;
    }
    const f = (this.failures.get(skill) ?? 0) + 1;
    if (f >= FAIL_LIMIT) {
      this.failures.delete(skill);
      this.cooldown.set(skill, FAIL_COOLDOWN);
    } else {
      this.failures.set(skill, f);
    }
  }

  decide(w: WorldModel): string {
    if (!w || !w.player) return 'noop';
    const frac = hpFraction(w);
    // Опасность меряем по реальной агрессии (aggroOnMe), а не по соседству:
    // в стартовой зоне враги в 18 ярдах есть почти всегда, и правило «рядом двое —
    // беги» превращало прогон в бесконечное бегство (418 смертей при 4 убийствах).
    const chased = aggressors(w).length;
    if (frac < CRIT_HP) return chased > 0 ? 'flee' : 'heal';
    if (frac < LOW_HP) return chased > 0 ? 'flee' : 'heal';
    // За нами бежит двое и больше — бой не выиграть (мобы быстрее игрока), уходим.
    if (chased >= CROWD_LIMIT) return 'flee';

    // тик перерывов
    for (const [skill, left] of [...this.cooldown.entries()]) {
      if (left - 1 <= 0) this.cooldown.delete(skill);
      else this.cooldown.set(skill, left - 1);
    }

    const phase = mapFsmToPhase(this.fsm.phase);
    let allowed = (PHASE_ALLOWED[phase] ?? []).filter((s) => !this.cooldown.has(s) && !this.disabled.has(s));

    // лечить полного — тратить решение впустую (порог HEAL_BELOW объявлен выше)
    if (frac >= HEAL_BELOW) allowed = allowed.filter((s) => s !== 'heal');

    // инвариант: активный квест нельзя взять заново
    if (hasActiveQuest(w) || hasReadyQuest(w)) allowed = allowed.filter((s) => s !== 'accept_quest');
    if (!hasActiveQuest(w) && !hasReadyQuest(w)) {
      allowed = allowed.filter((s) => s !== 'return_to_giver' && s !== 'turn_in_quest');
    }

    let selected = this.selectBest(allowed, w);
    if (selected === this.lastAction) {
      if (++this.repeatCount >= LOOP_THRESHOLD) {
        const alt = allowed.filter((s) => s !== selected);
        if (alt.length > 0) selected = alt[0];
        this.repeatCount = 0;
      }
    } else {
      this.repeatCount = 0;
    }
    this.lastAction = selected;
    this.memory.recordAction(selected);
    return selected;
  }

  /** Первый допустимый навык из приоритетного списка (порт selectBest). */
  private selectBest(allowed: string[], w: WorldModel): string {
    if (allowed.length === 0) return 'noop';
    const ready = readyQuest(w);
    const giverNear = availableGiverInRange(w, this.ranges.interactRange) !== null;
    const turnInNear = turnInNpcInRange(w, ready, this.ranges.interactRange) !== null;
    const active = hasActiveQuest(w);

    const priority: string[] = [];
    if (ready) priority.push(turnInNear ? 'turn_in_quest' : 'return_to_giver');
    if (!ready && !active && giverNear) priority.push('accept_quest');
    // Недолечен и никто не гонится — лечимся. Без этого правила heal выбирался
    // только на аварийных порогах (HP<30%), и агент часами стоял на 37% HP,
    // отказываясь от боя (NOT_NOW) и не восстанавливаясь: 229 таких решений.
    if (hpFraction(w) < HEAL_BELOW && aggressors(w).length === 0) priority.push('heal');
    if (hasMobInMeleeRange(w, this.ranges.meleeRange)) priority.push('farm');
    // Доступный по уровню моб в пределах FARM_TRIGGER_DIST — тоже повод драться:
    // иначе агент «прибывал» к цели и стоял, пока farm был на перерыве.
    else if (w.nearby.some((m) => m.dist <= FARM_TRIGGER_DIST && this.fightable(m, w))) {
      priority.push('farm');
    }
    if (lootInRange(w, this.ranges.interactRange)) priority.push('loot');
    if (active) priority.push('navigate');
    // Идти есть куда, даже если живых NPC не видно: слой карты (mapPins) знает,
    // где стоит квестодатель — так же устроен клиент в живом мире.
    if (
      !ready &&
      !active &&
      !giverNear &&
      (nearestAvailableGiver(w) ?? nearestTurnInNpc(w, ready) ?? nearestPin(w))
    ) {
      priority.push('navigate');
    }
    priority.push('explore');

    for (const p of priority) if (allowed.includes(p)) return p;
    return allowed[0];
  }

  /**
   * Кого мы готовы бить. Правило одно, а данные — разные в зависимости от мира:
   *   - стенд (entityTemplates=true): вид сущности известен → canFightMob по
   *     данным контента + проверка «не манекен» по абсолютному HP;
   *   - мир за бриджем (entityTemplates=false): вида нет, абсолютного HP нет →
   *     решаем по наблюдаемой Δуровня (то же правило levelDeltaMax).
   * Молча считать templateId известным здесь значило бы никогда не драться
   * за проводом: canFightMob('') вернул бы false.
   */
  private fightable(m: EntityView, w: WorldModel): boolean {
    const caps = this.caps;
    if (caps.entityTemplates) {
      return (
        canFightMob(m.templateId, w.player.level) &&
        m.maxHp <= UNKILLABLE_HP_FACTOR * Math.max(1, w.player.maxHp)
      );
    }
    return canFightObservedLevel(m.level - w.player.level);
  }
}

export function mapFsmToPhase(phase: QuestPhase): string {
  switch (phase) {
    case 'QUEST_NONE':
      return 'NO_QUEST';
    case 'FIND_GIVER':
      return 'FIND_GIVER';
    case 'ACCEPT':
      return 'ACCEPT';
    case 'DO_OBJECTIVE':
    case 'VERIFY_PROGRESS':
      return 'DO_OBJECTIVE';
    case 'RETURN_TO_GIVER':
      return 'RETURN_TO_GIVER';
    case 'TURN_IN':
      return 'TURN_IN';
    case 'QUEST_COMPLETE':
      return 'NO_QUEST';
    default:
      return 'NO_QUEST';
  }
}

export { readyQuest };
export type { EntityView };
