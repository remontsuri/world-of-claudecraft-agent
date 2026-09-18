/**
 * quest_policy.ts — какие квесты мы вообще способны пройти в headless-мире.
 *
 * Типы целей взяты из игры (QUESTS), а не придуманы: по 224 квестам их шесть —
 * kill, collect, interact, gather, escort, farm. Три последних непроходимы:
 *   - gather/farm: профессии — явный CUT headless env (headless/CLAUDE.md,
 *     запись от 2026-08-29): в action space нет ни сбора, ни посадки;
 *   - escort: действия сопровождения в ACTIONS нет.
 * kill/collect/interact проходимы: убийство (attack/ability_N), сбор лута
 * (interact по трупу), разговор/удар по объекту (interact).
 *
 * Отдельно — правило выбора квеста NPC: игра на `interact` выдаёт ПЕРВЫЙ
 * доступный квест из questIds, у которого giverNpcId совпал с templateId NPC
 * и нет completionEffect (sim.ts, talkToNpc: цикл по npc.questIds, ветки
 * turn-in -> accept). Выбирать квест при разговоре нельзя, поэтому агент
 * обязан предсказать, что ему дадут, и не говорить с тем, кто даст непроходимое.
 * Предсказание закреплено тестом tests/quest_policy.test.ts: если upstream
 * поменяет правило, тест упадёт, а не молча сломает поведение.
 */
import { QUESTS, QUEST_ORDER } from '../../game/src/sim/data';
import { mobLevelRange, type QuestDef } from '../facts';
import { PARAMS } from '../policy/params';

/** На сколько уровней выше нас моб, с которым мы ещё готовы драться.
 *  Заявлено до измерения: мобы зоны быстрее игрока (RUN_SPEED=7, волк 8, кабан 7.5,
 *  Old Greyjaw 8.5), поэтому бой не по уровню — это не риск, а гарантированная смерть. */
export const LEVEL_DELTA_MAX = PARAMS.levelDeltaMax;

/** По силам ли нам моб этого шаблона на нашем уровне (уровни — из данных игры). */
export function canFightMob(templateId: string, playerLevel: number, delta = LEVEL_DELTA_MAX): boolean {
  const r = mobLevelRange(templateId);
  if (!r) return false;
  return r.maxLevel <= playerLevel + delta;
}

/** Проходимые типы целей (наше действие: attack/ability_N и interact). */
/**
 * Можно ли бить цель, если её ВИД неизвестен (мир за бриджем: по RL-obs нет
 * templateId, есть только Δуровня относительно игрока). Правило то же, что и в
 * canFightMob — уровень не выше playerLevel + levelDeltaMax, — но применяется к
 * наблюдаемой дельте, а не к данным контента.
 */
export function canFightObservedLevel(levelDelta: number, delta = PARAMS.levelDeltaMax): boolean {
  if (!Number.isFinite(levelDelta)) return false;
  return levelDelta <= delta;
}

export const SUPPORTED_OBJECTIVE_TYPES = ['kill', 'collect', 'interact'] as const;

/** Непроходимые типы целей — с причиной. */
export const UNSUPPORTED_OBJECTIVE_TYPES: Record<string, string> = {
  gather: 'профессии вне action space headless env (CUT upstream, headless/CLAUDE.md 2026-08-29)',
  farm: 'фермерство вне action space headless env (CUT upstream, headless/CLAUDE.md 2026-08-29)',
  escort: 'сопровождение: в ACTIONS нет действия сопровождения',
};

function def(qid: string): QuestDef | undefined {
  return (QUESTS as Record<string, QuestDef>)[qid];
}

/** Сколько целей каждого типа в игре — факт для отчёта, а не наша оценка. */
export function objectiveTypeCounts(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const qid of QUEST_ORDER) {
    for (const o of def(qid)?.objectives ?? []) out[o.type] = (out[o.type] ?? 0) + 1;
  }
  return out;
}

/** Причины, по которым квест непроходим (пусто = проходим). */
export function incompletableReasons(qid: string): string[] {
  const q = def(qid);
  if (!q) return [`в игре нет квеста ${qid}`];
  const reasons: string[] = [];
  for (const o of q.objectives) {
    const why = UNSUPPORTED_OBJECTIVE_TYPES[o.type];
    if (why) reasons.push(`${o.type}: ${why}`);
  }
  return reasons;
}

export function isQuestCompletable(qid: string): boolean {
  return incompletableReasons(qid).length === 0;
}

/**
 * Приоритет квеста для выбора (меньше = лучше). Заявленная политика:
 *   0 — только убийства (гарантированно даёт kills, метрика J8);
 *   1 — убийства + сбор (нужен ещё лут с трупов);
 *   2 — только interact (разговор/удар по объекту, убийств не даёт);
 *   3 — только сбор (нужен лут, убийств не даёт напрямую).
 */
export function questPriority(qid: string): number {
  const types = (def(qid)?.objectives ?? []).map((o) => o.type);
  const has = (t: string) => types.includes(t);
  if (has('kill')) return has('collect') || has('interact') ? 1 : 0;
  if (has('interact')) return 2;
  if (has('collect')) return 3;
  return 4;
}

/**
 * Какой квест выдаст NPC при `interact` (правило игры, см. шапку файла).
 * `stateOf` — состояние квеста глазами игры ('available' | 'active' | ...).
 */
export function predictedAccept(
  npcTemplateId: string,
  questIds: string[],
  stateOf: (qid: string) => string,
): string | null {
  for (const qid of questIds) {
    const q = def(qid);
    if (!q) continue;
    if (q.giverNpcId !== npcTemplateId) continue;
    if ((q as unknown as Record<string, unknown>).completionEffect) continue;
    if (stateOf(qid) === 'available') return qid;
  }
  return null;
}

/** То же, но сразу с проверкой проходимости: null = говорить не о чем. */
export function predictedUsefulAccept(
  npcTemplateId: string,
  questIds: string[],
  stateOf: (qid: string) => string,
): string | null {
  const qid = predictedAccept(npcTemplateId, questIds, stateOf);
  return qid && isQuestCompletable(qid) ? qid : null;
}
