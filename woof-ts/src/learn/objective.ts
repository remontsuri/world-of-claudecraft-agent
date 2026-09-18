/**
 * objective.ts — ЦЕЛЕВАЯ ФУНКЦИЯ контура обучения, объявленная до измерения.
 *
 * Правило проекта: пороги и критерии объявляются ДО прогона, иначе подбор
 * параметров превращается в подгонку под результат. Поэтому функция живёт здесь,
 * отдельным файлом, печатается в начале тюнинга и пишется в каждый отчёт.
 *
 * Что мы считаем успехом агента (по убыванию важности):
 *   1. сданные квесты — смысл линии: агент играет в игру, а не бьёт манекен;
 *   2. убийства — доказательство, что бой работает (порог «прогон состоялся»);
 *   3. смерти — штраф: умерший агент теряет время и прогресс;
 *   4. скорость первой сдачи — ранний квест означает, что связка
 *      «найти NPC → взять → выполнить → сдать» живая;
 *   5. расход шагов мира — штраф за эффективность: при равном результате
 *      меньше суеты лучше (иначе тюнинг находит «бег по кругу ради убийств»).
 *
 * Веса подобраны так, чтобы квест доминировал над фармом, а фарм — над суетой:
 * один сданный квест (100) дороже 20 убийств (5·20=100) примерно впритык,
 * поэтому «фармить вместо квестов» выгодно лишь при большом перевесе убийств.
 */

export interface RunMetrics {
  kills: number;
  deaths: number;
  questsDone: number;
  firstTurnInStep: number;
  worldSteps: number;
  level: number;
  xp: number;
  copper: number;
  steps: number;
}

export const OBJECTIVE_WEIGHTS = {
  questDone: 100,
  kill: 5,
  death: -10,
  earlyTurnIn: 20,
  worldStep: -1 / 1000,
  levelUp: 25,
} as const;

/** Штраф за «первая сдача слишком поздно»: после этого шага бонус не даём. */
export const EARLY_TURN_IN_LIMIT = 40;

export function score(m: RunMetrics): number {
  const early = m.firstTurnInStep > 0 && m.firstTurnInStep <= EARLY_TURN_IN_LIMIT ? OBJECTIVE_WEIGHTS.earlyTurnIn : 0;
  return (
    m.questsDone * OBJECTIVE_WEIGHTS.questDone +
    m.kills * OBJECTIVE_WEIGHTS.kill +
    m.deaths * OBJECTIVE_WEIGHTS.death +
    (m.level - 1) * OBJECTIVE_WEIGHTS.levelUp +
    early +
    m.worldSteps * OBJECTIVE_WEIGHTS.worldStep
  );
}

/** Человекочитаемое объявление функции — печатается ДО первых измерений. */
export function describeObjective(): string[] {
  const w = OBJECTIVE_WEIGHTS;
  return [
    `score = ${w.questDone}·quests_done ${w.kill >= 0 ? '+' : '-'} ${Math.abs(w.kill)}·kills ${w.death >= 0 ? '+' : '-'} ${Math.abs(w.death)}·deaths ` +
      `${w.levelUp >= 0 ? '+' : '-'} ${Math.abs(w.levelUp)}·(level-1) + ${w.earlyTurnIn}·[first_turn_in ≤ ${EARLY_TURN_IN_LIMIT}] ` +
      `${w.worldStep >= 0 ? '+' : '-'} ${Math.abs(w.worldStep)}·world_steps`,
    'смысл весов: квест важнее фарма, фарм важнее суеты; смерть — штраф; ранняя сдача — бонус',
    'объявлено до измерения; изменение весов = новая гипотеза и новая запись в learning/history.jsonl',
  ];
}

/** Сплит сидов: на train подбираем, на val проверяем, что не переобучились.
 *  Сиды не пересекаются — иначе «улучшение» может быть подгонкой под один мир. */
export interface SeedSplit {
  train: number[];
  val: number[];
}

export function seedSplit(train: number[], val: number[]): SeedSplit {
  const overlap = train.filter((s) => val.includes(s));
  if (overlap.length > 0) {
    throw new Error(`сиды train и val пересекаются (${overlap.join(', ')}) — это переобучение, а не проверка`);
  }
  if (train.length === 0) throw new Error('пустой набор train-сидов: сравнивать нечего');
  return { train, val };
}

/** Средний скор по сидам + разброс: один сид — ещё не результат (см. D6: сид 7 хрупок). */
export function aggregate(scores: number[]): { mean: number; min: number; max: number; n: number } {
  if (scores.length === 0) return { mean: 0, min: 0, max: 0, n: 0 };
  const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
  return { mean, min: Math.min(...scores), max: Math.max(...scores), n: scores.length };
}
