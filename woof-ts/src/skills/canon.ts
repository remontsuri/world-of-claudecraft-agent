/**
 * canon.ts — канон навыков. Порт core/SkillIndex.java из Java-линии.
 *
 * Правило прежнее: навык — только из канона, неизвестное имя — исключение,
 * а не молчаливый no-op. Плюс честная граница: часть канона в headless-мире
 * невыполнима, и это заявлено явно (с причиной), а не спрятано.
 */

/** 13 канонических навыков (SkillIndex.SKILLS в Java-линии). */
export const CANON = [
  'farm',
  'loot',
  'accept_quest',
  'turn_in_quest',
  'sell_junk',
  'gather',
  'craft',
  'heal',
  'equip',
  'buy',
  'cast_frostbolt',
  'cast_fireball',
  'craft_item',
] as const;

export type CanonicalSkill = (typeof CANON)[number];

/** Алиасы из Java-линии (SkillIndex.ALIASES). */
export const ALIASES: Record<string, string> = {
  turn_in: 'turn_in_quest',
  sell: 'sell_junk',
};

/** Композиты исполнителя: их выбирает арбитраж, но в канон навыков не входят. */
export const COMPOSITES = ['navigate', 'return_to_giver', 'explore', 'flee', 'noop'] as const;

export type CompositeSkill = (typeof COMPOSITES)[number];
export type SkillName = CanonicalSkill | CompositeSkill;

export const ALL_SKILLS: readonly string[] = [...CANON, ...COMPOSITES];

/** Привести имя к канону. Незнающее имя — исключение (правило проекта). */
export function canonical(name: string): string {
  const resolved = ALIASES[name] ?? name;
  if ((ALL_SKILLS as readonly string[]).includes(resolved)) return resolved;
  throw new Error(
    `навык "${name}" не из канона; канон: ${CANON.join(', ')}; композиты: ${COMPOSITES.join(', ')}`,
  );
}

const PROFESSION_CUT =
  'профессии/торговля вне action space headless env (явный CUT upstream: headless/CLAUDE.md, ' +
  'запись от 2026-08-29) — в мире нет ни продавца, ни станции, ни сбора';

/** Навыки канона, которые в headless-мире невыполнимы, с причиной. */
export const HEADLESS_UNSUPPORTED: Record<string, string> = {
  sell_junk: PROFESSION_CUT,
  buy: PROFESSION_CUT,
  gather: PROFESSION_CUT,
  craft: PROFESSION_CUT,
  craft_item: PROFESSION_CUT,
  equip: 'экипировка в headless-мире автоматическая (Sim: autoEquip=true), отдельного действия нет',
};

export function isSupported(skill: string): boolean {
  return !Object.prototype.hasOwnProperty.call(HEADLESS_UNSUPPORTED, canonical(skill));
}

export function unsupportedReason(skill: string): string | null {
  return HEADLESS_UNSUPPORTED[canonical(skill)] ?? null;
}
