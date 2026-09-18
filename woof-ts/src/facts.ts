/**
 * facts.ts — факты об игре. НИ ОДНОГО числа, переписанного руками.
 *
 * Всё импортируется из первоисточника (game -> src/sim, см. tools/setup_game.sh).
 * Это осознанный отказ от практики, которая уже дважды стоила нам дефектов:
 *   - в архивной fly-линии obs=607 был захардкожен в train.py (баг B3);
 *   - Java-клиент спрашивал health через POST, а настоящий мост отдавал его
 *     только на GET /health — e2e был зелёный, живой прогон упал бы с кодом 2.
 * Здесь такой класс расхождений невозможен: константы берутся из игры.
 *
 * Игра: World of ClaudeCraft (https://github.com/levy-street/world-of-claudecraft),
 * лицензия MIT. Мы её не модифицируем, только читаем и запускаем.
 */
import { ACTIONS, NUM_ACTIONS, obsSize } from '../game/src/sim/obs';
import { CAMPS, CLASSES, MOBS, NPCS, QUEST_ORDER, QUESTS, abilitiesKnownAt } from '../game/src/sim/data';
import type { CampDef, NpcDef } from '../game/src/sim/types';
import { DT, GCD, INTERACT_RANGE, MAX_LEVEL, MELEE_RANGE, PLAYER_INTEREST_DROP_RADIUS } from '../game/src/sim/types';
import { WORLD_MAX_X, WORLD_MAX_Z, WORLD_MIN_Z } from '../game/src/sim/data';

export interface GameFacts {
  readonly actions: readonly string[];
  readonly numActions: number;
  readonly abilitySlots: number;
  readonly obsSize: number;
  readonly maxLevel: number;
  readonly meleeRange: number;
  readonly interactRange: number;
  readonly questCount: number;
  readonly classes: readonly string[];
  /** Действия, не являющиеся способностями: их число = numActions - abilitySlots. */
  readonly nonAbilityActions: readonly string[];
}

/** Факты текущей сборки игры (вычисляются один раз). */
export function gameFacts(): GameFacts {
  const abilitySlots = ACTIONS.filter((a) => a.startsWith('ability_')).length;
  return {
    actions: ACTIONS as readonly string[],
    numActions: NUM_ACTIONS,
    abilitySlots,
    obsSize: obsSize(),
    maxLevel: MAX_LEVEL,
    meleeRange: MELEE_RANGE,
    interactRange: INTERACT_RANGE,
    questCount: QUEST_ORDER.length,
    classes: Object.keys(CLASSES),
    nonAbilityActions: ACTIONS.filter((a) => !a.startsWith('ability_')) as readonly string[],
  };
}

/**
 * Способности класса в порядке изучения: слот ability_N -> id способности.
 * Форма элемента в игре — строка-id либо объект с id; берём то, что реально есть,
 * и громко падаем, если не смогли прочитать ни одного имени (молча вернуть
 * пустой список значило бы сломать маппинг способностей незаметно).
 */
export function classAbilities(playerClass: string): readonly string[] {
  const cls = (CLASSES as Record<string, { abilities: unknown[] }>)[playerClass];
  if (!cls) {
    throw new Error(
      `неизвестный класс "${playerClass}"; доступны: ${Object.keys(CLASSES).join(', ')}`,
    );
  }
  const ids = cls.abilities.map((a) => {
    if (typeof a === 'string') return a;
    const obj = a as { id?: string; abilityId?: string };
    const id = obj?.id ?? obj?.abilityId;
    if (typeof id !== 'string' || !id) {
      throw new Error(
        `не смог прочитать id способности класса "${playerClass}": ${JSON.stringify(a).slice(0, 120)}`,
      );
    }
    return id;
  });
  if (ids.length === 0) throw new Error(`у класса "${playerClass}" пустой список способностей`);
  return ids;
}

/** Определение квеста из игры (цели, кто даёт, кто принимает). */
export function questDef(questId: string) {
  const q = (QUESTS as Record<string, QuestDef>)[questId];
  if (!q) throw new Error(`в игре нет квеста "${questId}"`);
  return q;
}

export interface QuestObjectiveDef {
  type: string;
  targetMobId?: string;
  targetNpcId?: string;
  /** Для collect: какой предмет нужен. */
  itemId?: string;
  /** Для interact: по какому объекту мира взаимодействовать. */
  targetObjectItemId?: string;
  count: number;
  label?: string;
}

export interface QuestDef {
  id: string;
  name: string;
  giverNpcId?: string;
  turnInNpcId?: string;
  objectives: QuestObjectiveDef[];
  xpReward?: number;
  copperReward?: number;
}

export const questOrder: readonly string[] = QUEST_ORDER as readonly string[];

/** itemId -> шаблоны мобов, с которых он падает (таблицы лута игры, MOBS[*].loot). */
const DROP_SOURCES: Map<string, string[]> = (() => {
  const m = new Map<string, string[]>();
  for (const [templateId, mob] of Object.entries(MOBS as Record<string, { loot?: unknown[] }>)) {
    for (const entry of (mob?.loot ?? []) as Array<{ itemId?: string }>) {
      if (!entry?.itemId) continue;
      const list = m.get(entry.itemId);
      if (list) list.push(templateId);
      else m.set(entry.itemId, [templateId]);
    }
  }
  return m;
})();

/**
 * С каких мобов падает предмет цели collect. Без этого агент не знает, кого бить
 * ради «5 шкур кабана», и мы бы гадали вместо чтения данных игры.
 */
export function mobsDropping(itemId: string | undefined): readonly string[] {
  if (!itemId) return [];
  return DROP_SOURCES.get(itemId) ?? [];
}

export interface CampFact {
  mobId: string;
  x: number;
  z: number;
  radius: number;
  count: number;
}

/**
 * Лагеря мобов из данных игры (CAMPS = ZONE1_CAMPS + ZONE2_CAMPS + ...).
 * Это знание уровня карты и текста квеста («Old Greyjaw бродит в глухих лесах
 * севернее волчьих троп»), а не глобальное зрение: сами мобы агент видит только
 * в VIEW_RADIUS=60, как в RL-наблюдении игры.
 */
export function campsFor(mobId: string): CampFact[] {
  return allCamps().filter((c) => c.mobId === mobId);
}

/** Все лагеря мобов мира (те же данные, без фильтра). */
export function allCamps(): CampFact[] {
  return (CAMPS as CampDef[]).map((c) => ({
    mobId: c.mobId,
    x: c.center.x,
    z: c.center.z,
    radius: c.radius,
    count: c.count,
  }));
}

/** Диапазон уровней моба из данных игры (MobTemplate.minLevel/maxLevel). */
export function mobLevelRange(templateId: string): { minLevel: number; maxLevel: number } | null {
  const m = (MOBS as Record<string, { minLevel?: number; maxLevel?: number }>)[templateId];
  if (!m) return null;
  return { minLevel: m.minLevel ?? 0, maxLevel: m.maxLevel ?? 0 };
}

export interface NpcPin {
  templateId: string;
  name: string;
  x: number;
  z: number;
  questIds: string[];
  /** Есть ли у NPC торговый стол (онлайн-мир: сумки можно разгружать продажей). */
  vendor: boolean;
}

/**
 * Статические пины NPC из контент-данных игры (`NPCS[*].pos` + `questIds`).
 * Это знание уровня КАРТЫ клиента, а не наблюдение за миром: живой мир реплицирует
 * сущности только в пределах интереса — `PLAYER_INTEREST_DROP_RADIUS = 100`
 * (src/sim/types.ts:56), а headless env держит собственный throttle 80
 * (headless/env_server.ts:120). Поэтому «видеть всех NPC мира» агент не может,
 * но знать, где на карте стоит квестодатель, — может, как любой игрок.
 */
export function npcPins(): NpcPin[] {
  return Object.values(NPCS as Record<string, NpcDef>).map((n) => ({
    templateId: n.id,
    name: n.name,
    x: n.pos.x,
    z: n.pos.z,
    questIds: n.questIds ?? [],
    vendor: (n.vendorItems?.length ?? 0) > 0 || !!n.market,
  }));
}

/** Радиус реплицируемого вида в живой игре (за его пределами клиент сущность не получает). */
export const INTEREST_DROP_RADIUS = PLAYER_INTEREST_DROP_RADIUS;

/** Границы мира: нужны бриджу, чтобы восстановить АБСОЛЮТНЫЕ координаты игрока
 *  из нормированного RL-obs (obs.ts: `p.pos.x / WORLD_MAX_X` и z-нормаль).
 *  Значения — из данных игры, не из памяти. */
export const WORLD_BOUNDS = { maxX: WORLD_MAX_X, minZ: WORLD_MIN_Z, maxZ: WORLD_MAX_Z } as const;

/** Длительность глобального кулдауна, сек (obs кодирует gcdRemaining / GCD). */
export const GCD_SECONDS = GCD;

/** Максимальный уровень (obs кодирует level / MAX_LEVEL). */
export const LEVEL_CAP = MAX_LEVEL;

/** Длительность одного тика симуляции, сек (20 тиков = 1 сек мира).
 *  Бриджу нужно, чтобы восстановить время мира из числа шагов: по проводу
 *  sim.time не отдаётся, а frameSkip известен из конфига эпизода. */
export const TICK_SECONDS = DT;

/** Дальность взаимодействия (лут/объекты/разговор с NPC) — константа игры.
 *  Бриджу нужна, чтобы понимать, в каком радиусе мир вообще показывает
 *  «ближайший взаимодействуемый объект» (obs.interactable). */
export const INTERACT_RANGE_YARDS = INTERACT_RANGE;

/**
 * Способности, известные классу на данном уровне, в порядке изучения:
 * индекс = слот ability_N. Это ТОТ ЖЕ источник, которым игра заполняет sim.known
 * (abilitiesKnownAt из src/sim/content/classes.ts), поэтому нумерация слотов у
 * стенда и у бриджа совпадает. `doneQuestIds` влияет на выдачу некоторых
 * способностей — по проводу набор «done» виден точно (obs.quests), поэтому
 * аргумент восстанавливается без догадок.
 */
export function knownAbilities(
  playerClass: string,
  level: number,
  doneQuestIds: ReadonlySet<string> = new Set<string>(),
): Array<string | null> {
  // mods = undefined: игра подставляет собственные модификаторы талантов по
  // умолчанию (пустой объект {} ломает applyTalentMods — проверено).
  const known = abilitiesKnownAt(
    playerClass as never,
    level,
    undefined,
    doneQuestIds,
  ) as Array<{ def?: { id?: string } }>;
  const slots = gameFacts().abilitySlots;
  return Array.from({ length: slots }, (_, i) => known[i]?.def?.id ?? null);
}
