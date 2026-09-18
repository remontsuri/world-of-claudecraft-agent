/**
 * types.ts — модель мира, которую видит агент.
 *
 * Порт WorldState/Entity/QuestEntry/PlayerState из Java-линии (woof-agent),
 * но без HTTP-моста: поля берутся прямо из Sim игры. Отсюда же — производные
 * признаки, на которых стоят FSM и арбитраж (в Java они жили в WorldState).
 */

export type EntityKind = 'mob' | 'npc' | 'object' | 'player';

export interface PlayerView {
  hp: number;
  maxHp: number;
  resource: number;
  maxResource: number;
  resourceType: string;
  level: number;
  xp: number;
  x: number;
  z: number;
  facing: number;
  dead: boolean;
  inCombat: boolean;
  autoAttack: boolean;
  resting: boolean;
  playerClass: string;
  targetId: number | null;
}

export interface EntityView {
  id: number;
  kind: EntityKind;
  templateId: string;
  name: string;
  level: number;
  hp: number;
  maxHp: number;
  hostile: boolean;
  dead: boolean;
  /** Труп, который ещё можно обыскать. */
  lootable: boolean;
  /** Квесты, которые выдаёт/принимает этот NPC. */
  questIds: string[];
  /** Из questIds — те, что доступны нам прямо сейчас (состояние 'available' в игре).
   *  Без этого агент долбит NPC, у которого квест закрыт по классу/пререквизиту:
   *  так было с q_hub_healing_numbers (requiredClass + requiresUsableHealAbility). */
  availableQuests: string[];
  /** Квест, который игра выдаст этому NPC при `interact`, если он проходим для нас
   *  (quest_policy: gather/farm/escort в headless-мире непроходимы). Пусто = говорить не о чем. */
  completableQuests: string[];
  aggroOnMe: boolean;
  /** Абсолютные координаты (в игре они есть; в RL-obs их нет). */
  x: number;
  z: number;
  /** Дистанция до игрока, ярды. */
  dist: number;
  /** Относительный пеленг: 0 = прямо по курсу, >0 = слева (turn_left уменьшает). */
  bearing: number;
}

export interface ObjectiveView {
  type: string;
  targetMobId?: string;
  targetNpcId?: string;
  /** collect: предмет, который нужно собрать (падает с мобов — см. facts.mobsDropping). */
  itemId?: string;
  /** interact: объект мира, с которым нужно взаимодействовать. */
  targetObjectItemId?: string;
  required: number;
  have: number;
  label?: string;
}

export type QuestStateName = 'available' | 'active' | 'ready' | 'done' | 'other';

export interface QuestView {
  id: string;
  name: string;
  state: QuestStateName;
  objectives: ObjectiveView[];
  progress: number;
  required: number;
  giverNpcId?: string;
  turnInNpcId?: string;
}

export interface Counters {
  kills: number;
  deaths: number;
  questsCompleted: number;
  questProgress: number;
  xpGained: number;
  levelUps: number;
  damageDealt: number;
  damageTaken: number;
  lootCopper: number;
}

/** Точка на карте из контент-данных игры: где стоит NPC и что у него для нас есть.
 *  Это НЕ наблюдение за живой сущностью: в онлайн-мире клиент знает карту и журнал
 *  квестов, но сами сущности получает только в радиусе интереса
 *  (PLAYER_INTEREST_DROP_RADIUS=100; headless env — throttle 80). */
export interface MapPin {
  templateId: string;
  name: string;
  x: number;
  z: number;
  /** giver — у NPC есть для нас проходимый квест; turnin — он принимает наш квест. */
  kind: 'giver' | 'turnin';
  questId: string;
  /** Дистанция от игрока, ярды. */
  dist: number;
}

export interface WorldModel {
  step: number;
  time: number;
  player: PlayerView;
  target: EntityView | null;
  /** Живые враждебные мобы в радиусе наблюдения, ближайшие первыми. */
  nearby: EntityView[];
  /** NPC в радиусе видимости NPC (см. npcViewRadius в sim_world). */
  npcs: EntityView[];
  /** Объекты мира в радиусе наблюдения: цели interact-квестов, контейнеры лута. */
  objects: EntityView[];
  /** Трупы, которые можно обыскать. */
  corpses: EntityView[];
  /** Слой карты: статические пины NPC из контент-данных (см. MapPin). */
  mapPins: MapPin[];
  /** Квесты: из журнала игрока + доступные у видимых NPC. */
  quests: QuestView[];
  counters: Counters;
  copper: number;
}

export const VIEW_RADIUS = 60; // ярдов: тот же радиус, что и у RL-наблюдения (obs.ts: d < 60)

// --- производные признаки (в Java — методы WorldState) ----------------------

export function hpFraction(w: WorldModel): number {
  if (w.player.maxHp <= 0) return 0;
  return w.player.hp / w.player.maxHp;
}

export function isDanger(w: WorldModel): boolean {
  return w.player.dead || hpFraction(w) < 0.3 || w.player.inCombat;
}

export function hasMobInMeleeRange(w: WorldModel, meleeRange: number): boolean {
  return w.nearby.some((e) => !e.dead && e.hostile && e.dist <= meleeRange);
}

export function activeQuest(w: WorldModel): QuestView | null {
  return w.quests.find((q) => q.state === 'active') ?? null;
}

export function readyQuest(w: WorldModel): QuestView | null {
  return w.quests.find((q) => q.state === 'ready') ?? null;
}

export function hasActiveQuest(w: WorldModel): boolean {
  return activeQuest(w) !== null;
}

export function hasReadyQuest(w: WorldModel): boolean {
  return readyQuest(w) !== null;
}

/** Любой NPC с квестами в радиусе взаимодействия (признак «мы у людей»). */
export function questGiverInRange(w: WorldModel, interactRange: number): EntityView | null {
  return (
    w.npcs
      .filter((n) => n.questIds.length > 0 && n.dist <= interactRange)
      .sort((a, b) => a.dist - b.dist)[0] ?? null
  );
}

/** NPC в радиусе, у которого есть ДОСТУПНЫЙ и ПРОХОДИМЫЙ для нас квест. */
export function availableGiverInRange(w: WorldModel, interactRange: number): EntityView | null {
  return (
    w.npcs
      .filter((n) => n.completableQuests.length > 0 && n.dist <= interactRange)
      .sort((a, b) => a.dist - b.dist)[0] ?? null
  );
}

/** Враги в радиусе, которые РЕАЛЬНО могут нас убить: не «неубиваемые» (учебный
 *  манекен на 999999 HP во дворе — hostile, но не угроза, и его нельзя считать
 *  «толпой», иначе агент вечно убегает от собственного тренировочного двора). */
export function threateningNear(w: WorldModel, radius: number, hpCapFactor = 5): EntityView[] {
  const cap = hpCapFactor * Math.max(1, w.player.maxHp);
  return w.nearby.filter((m) => m.dist <= radius && m.maxHp <= cap);
}

/** Мобы, которые РЕАЛЬНО дерутся с нами (aggroTargetId = мы), а не просто стоят
 *  рядом. В стартовой зоне враги в 18 ярдах есть почти всегда, но атакуют они
 *  только после аггро (aggroRadius=10 у зверя зоны 1) — поэтому решения «бежать/
 *  лечиться» принимаются по агрессии, иначе агент вечно убегает от пейзажа. */
export function aggressors(w: WorldModel, radius = Number.POSITIVE_INFINITY): EntityView[] {
  return w.nearby.filter((m) => m.aggroOnMe && m.dist <= radius);
}

/** Ближайшая точка карты нужного рода (по умолчанию — любая). */
export function nearestPin(w: WorldModel, kind?: 'giver' | 'turnin'): MapPin | null {
  return w.mapPins.filter((p) => !kind || p.kind === kind).sort((a, b) => a.dist - b.dist)[0] ?? null;
}

/** Ближайший объект мира по шаблону (цель interact-квеста, контейнер). */
export function nearestObject(w: WorldModel, templateId: string | undefined): EntityView | null {
  if (!templateId) return null;
  return w.objects.filter((o) => o.templateId === templateId).sort((a, b) => a.dist - b.dist)[0] ?? null;
}

/** NPC в радиусе, который принимает готовый квест. */
export function turnInNpcInRange(w: WorldModel, q: QuestView | null, interactRange: number): EntityView | null {
  if (!q) return null;
  const template = q.turnInNpcId ?? q.giverNpcId;
  return (
    w.npcs.filter((n) => (template ? n.templateId === template : n.questIds.includes(q.id)) && n.dist <= interactRange)
      .sort((a, b) => a.dist - b.dist)[0] ?? null
  );
}

/** Ближайший NPC с доступным проходимым квестом (без ограничения радиуса) — цель navigate. */
export function nearestAvailableGiver(w: WorldModel): EntityView | null {
  return w.npcs.filter((n) => n.completableQuests.length > 0).sort((a, b) => a.dist - b.dist)[0] ?? null;
}

/** Ближайший NPC, принимающий наш готовый квест (без ограничения радиуса). */
export function nearestTurnInNpc(w: WorldModel, q: QuestView | null): EntityView | null {
  if (!q) return null;
  const template = q.turnInNpcId ?? q.giverNpcId;
  return (
    w.npcs
      .filter((n) => (template ? n.templateId === template : n.questIds.includes(q.id)))
      .sort((a, b) => a.dist - b.dist)[0] ?? null
  );
}

/** Ближайший NPC с квестами (любыми) — запасная цель, если доступных не видно. */
export function nearestGiver(w: WorldModel): EntityView | null {
  return w.npcs.filter((n) => n.questIds.length > 0).sort((a, b) => a.dist - b.dist)[0] ?? null;
}

/** Ближайший труп, который ещё можно обыскать. */
export function lootInRange(w: WorldModel, interactRange: number): EntityView | null {
  return (
    w.corpses.filter((c) => c.lootable && c.dist <= interactRange).sort((a, b) => a.dist - b.dist)[0] ??
    null
  );
}

/** Живой моб требуемого типа (цель квеста), ближайший. */
export function nearestQuestMob(w: WorldModel, targetMobId: string | undefined): EntityView | null {
  if (!targetMobId) return null;
  return (
    w.nearby.filter((m) => !m.dead && m.templateId === targetMobId).sort((a, b) => a.dist - b.dist)[0] ??
    null
  );
}
