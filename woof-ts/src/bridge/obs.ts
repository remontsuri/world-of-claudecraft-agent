/**
 * bridge/obs.ts — декодер RL-наблюдения игры в нашу модель мира.
 *
 * Зачем: headless env upstream (headless/env_server.ts) отдаёт агенту НЕ сущности,
 * а вектор чисел `obs` длиной obsSize(). Всё, что бридж знает о мире, он обязан
 * взять из этого вектора и из `info` (счётчики) — никаких других источников нет.
 *
 * Раскладка НЕ захардкожена: смещения выводятся из фактов игры (gameFacts) и
 * сверяются с obsSize() при построении, поэтому изменение баланса/контента
 * upstream ломает декодер громко, а не тихо сдвигает поля.
 *
 * Порядок полей — ровно как в encodeObs (src/sim/obs.ts):
 *   self(16) | abilities(2×ABILITY_SLOTS) | target(9) | nearest mobs(6×N) |
 *   proximity interactable(5) | quests(2×QUEST_ORDER.length) | paladin(3)
 *
 * Что по проводу НЕ восстанавливается (объявлено в capabilities бриджа):
 *   - id сущностей: obs даёт только «ближайших» без личности → entityIdentity='slot';
 *   - templateId (вид): есть лишь уровень относительно игрока → entityTemplates=false;
 *   - абсолютное HP/координаты сущностей: только доли и пеленг → entityAbsoluteHp=false;
 *   - состояние квеста 'available': в obs ноль НЕРАЗЛИЧИМ между available и
 *     none/failed, поэтому декодер возвращает 'other' и никогда не угадывает.
 */
import { GCD_SECONDS, LEVEL_CAP, WORLD_BOUNDS, classAbilities, gameFacts, questOrder, type GameFacts } from '../facts';

/** Сколько «ближайших мобов» кодирует obs. В игре это локальная константа
 *  NEARBY_MOBS (не экспортируется), поэтому выводим её из общей длины obs. */
export interface ObsLayout {
  readonly self: number;
  readonly abilities: number;
  readonly abilitySlots: number;
  readonly target: number;
  readonly mobs: number;
  readonly nearbyMobSlots: number;
  readonly interactable: number;
  readonly quests: number;
  readonly paladin: number;
  readonly total: number;
}

const SELF_FIELDS = 16;
const TARGET_FIELDS = 9;
const MOB_FIELDS = 6;
const INTERACTABLE_FIELDS = 5;
const QUEST_FIELDS = 2;
const PALADIN_FIELDS = 3;

export function obsLayout(f: GameFacts = gameFacts()): ObsLayout {
  const abilities = SELF_FIELDS;
  const abilitySlots = f.abilitySlots;
  const target = abilities + abilitySlots * 2;
  const mobs = target + TARGET_FIELDS;
  const rest = SELF_FIELDS + abilitySlots * 2 + TARGET_FIELDS + INTERACTABLE_FIELDS + f.questCount * QUEST_FIELDS + PALADIN_FIELDS;
  const nearbyMobSlots = (f.obsSize - rest) / MOB_FIELDS;
  if (!Number.isInteger(nearbyMobSlots) || nearbyMobSlots < 0) {
    throw new Error(
      `не удалось вывести число слотов «ближайших мобов» из obs: obsSize=${f.obsSize}, ` +
        `abilitySlots=${abilitySlots}, questCount=${f.questCount} — раскладка upstream изменилась`,
    );
  }
  const interactable = mobs + nearbyMobSlots * MOB_FIELDS;
  const quests = interactable + INTERACTABLE_FIELDS;
  const paladin = quests + f.questCount * QUEST_FIELDS;
  const total = paladin + PALADIN_FIELDS;
  if (total !== f.obsSize) {
    throw new Error(`раскладка obs не сходится: вычислено ${total}, игра сообщает ${f.obsSize}`);
  }
  return { self: 0, abilities, abilitySlots, target, mobs, nearbyMobSlots, interactable, quests, paladin, total };
}

export interface DecodedAbility {
  slot: number;
  /** id способности из набора класса (порядок изучения = номер слота). null, если слот за пределами набора класса. */
  abilityId: string | null;
  ready: boolean;
  /** Доля оставшегося кулдауна (1 = только что ушёл, 0 = готов). */
  cooldownFrac: number;
}

export interface DecodedTarget {
  present: boolean;
  hpFrac: number;
  /** level - playerLevel, восстановленный из clamp((lvl-pLvl)/5, -1, 1). */
  levelDelta: number;
  dist: number;
  /** Относительный пеленг, рад: 0 = прямо по курсу. */
  bearing: number;
  hostile: boolean;
  /** Мёртв, но обыскиваем (труп). */
  lootable: boolean;
  aggroOnMe: boolean;
}

export interface DecodedMob {
  dist: number;
  bearing: number;
  hpFrac: number;
  levelDelta: number;
  aggroOnMe: boolean;
}

export type InteractableKind = 'corpse' | 'object' | 'npc';

export interface DecodedInteractable {
  present: boolean;
  kind: InteractableKind | null;
  dist: number;
  bearing: number;
}

export type DecodedQuestState = 'active' | 'ready' | 'done' | 'other';

export interface DecodedQuest {
  id: string;
  state: DecodedQuestState;
  /** Доля выполнения (have/total по всем целям), 0..1. */
  progress: number;
}

export interface DecodedObs {
  /** Доля HP и ресурса (абсолютные значения по проводу не отдаются). */
  hpFrac: number;
  resourceFrac: number;
  level: number;
  xpFrac: number;
  /** Абсолютные координаты игрока: восстанавливаются из нормированных значений
   *  obs и границ мира (данные игры). Точность — float64, как в sim. */
  x: number;
  z: number;
  facing: number;
  gcdFrac: number;
  castFrac: number;
  dead: boolean;
  inCombat: boolean;
  autoAttack: boolean;
  resting: boolean;
  abilities: DecodedAbility[];
  target: DecodedTarget;
  /** Живые враждебные мобы в радиусе 60 ярдов, ближайшие первыми (пустые слоты отброшены). */
  mobs: DecodedMob[];
  interactable: DecodedInteractable;
  quests: DecodedQuest[];
  paladin: [number, number, number];
}

/** dist/40 обрезан сверху значением 1.5 — это и есть «пустой слот» (60 ярдов). */
const MOB_DIST_SCALE = 40;
const EMPTY_MOB_DIST = 1.5 * MOB_DIST_SCALE;

function bearingOf(sin: number, cos: number): number {
  return Math.atan2(sin, cos);
}

export function decodeObs(obs: number[], playerClass = 'warrior', f: GameFacts = gameFacts()): DecodedObs {
  if (!Array.isArray(obs) || obs.length !== f.obsSize) {
    throw new Error(`obs должен быть массивом длины ${f.obsSize}, получено ${Array.isArray(obs) ? obs.length : typeof obs}`);
  }
  const L = obsLayout(f);
  const kit = classAbilities(playerClass);

  const abilities: DecodedAbility[] = [];
  for (let i = 0; i < L.abilitySlots; i++) {
    abilities.push({
      slot: i,
      abilityId: kit[i] ?? null,
      ready: obs[L.abilities + i * 2] === 1,
      cooldownFrac: obs[L.abilities + i * 2 + 1],
    });
  }

  const t = L.target;
  const target: DecodedTarget = {
    present: obs[t] === 1,
    hpFrac: obs[t + 1],
    levelDelta: Math.round(obs[t + 2] * 5),
    dist: obs[t + 3] * MOB_DIST_SCALE,
    bearing: bearingOf(obs[t + 4], obs[t + 5]),
    hostile: obs[t + 6] === 1,
    lootable: obs[t + 7] === 1,
    aggroOnMe: obs[t + 8] === 1,
  };

  const mobs: DecodedMob[] = [];
  for (let k = 0; k < L.nearbyMobSlots; k++) {
    const o = L.mobs + k * MOB_FIELDS;
    const dist = obs[o] * MOB_DIST_SCALE;
    if (dist >= EMPTY_MOB_DIST - 1e-9) continue; // пустой слот (или ровно граница радиуса)
    mobs.push({
      dist,
      bearing: bearingOf(obs[o + 1], obs[o + 2]),
      hpFrac: obs[o + 3],
      levelDelta: Math.round(obs[o + 4] * 5),
      aggroOnMe: obs[o + 5] === 1,
    });
  }

  const i0 = L.interactable;
  const typeCode = obs[i0 + 4];
  const kind: InteractableKind | null =
    Math.abs(typeCode - 0.33) < 1e-6 ? 'corpse' : Math.abs(typeCode - 0.66) < 1e-6 ? 'object' : typeCode === 1 ? 'npc' : null;
  const interactable: DecodedInteractable = {
    present: obs[i0] === 1,
    kind,
    dist: obs[i0 + 1] * MOB_DIST_SCALE,
    bearing: bearingOf(obs[i0 + 2], obs[i0 + 3]),
  };

  const order = questOrder;
  const quests: DecodedQuest[] = [];
  for (let i = 0; i < order.length; i++) {
    const code = obs[L.quests + i * 2];
    const state: DecodedQuestState =
      code === 1 ? 'done' : Math.abs(code - 0.66) < 1e-6 ? 'ready' : Math.abs(code - 0.33) < 1e-6 ? 'active' : 'other';
    quests.push({ id: order[i], state, progress: obs[L.quests + i * 2 + 1] });
  }

  const zHalf = (WORLD_BOUNDS.maxZ - WORLD_BOUNDS.minZ) / 2;
  return {
    hpFrac: obs[0],
    resourceFrac: obs[1],
    level: Math.round(obs[2] * LEVEL_CAP),
    xpFrac: obs[3],
    x: obs[4] * WORLD_BOUNDS.maxX,
    z: obs[5] * zHalf + (WORLD_BOUNDS.minZ + WORLD_BOUNDS.maxZ) / 2,
    facing: bearingOf(obs[6], obs[7]),
    gcdFrac: obs[8],
    castFrac: obs[9],
    dead: obs[10] === 1,
    inCombat: obs[11] === 1,
    autoAttack: obs[12] === 1,
    resting: obs[14] === 1,
    abilities,
    target,
    mobs,
    interactable,
    quests,
    paladin: [obs[L.paladin], obs[L.paladin + 1], obs[L.paladin + 2]],
  };
}

/** Готовность способностей в том виде, в каком их ждёт агент (слот → имя). */
export function readyAbilities(d: DecodedObs): string[] {
  return d.abilities.filter((a) => a.ready && a.abilityId).map((a) => a.abilityId as string);
}

/** Доля GCD: 0 = готов, 1 = только что потрачен (obs: gcdRemaining / GCD). */
export function gcdSeconds(d: DecodedObs): number {
  return d.gcdFrac * GCD_SECONDS;
}
