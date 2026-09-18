/**
 * verify_facts.ts — сверка фактов, которые агент ИМПОРТИРУЕТ из дерева игры.
 *
 * Смысл: агент не хранит игровых чисел у себя (правило линии: факты — только
 * импортом из upstream levy-street/world-of-claudecraft). Значит при смене
 * версии игры молча поехать может всё: размер наблюдения, словарь действий,
 * таблица лута, уровни мобов, радиусы. Этот скрипт падает с внятным сообщением,
 * если дерево игры разошлось с тем, на чём стоят наши политики.
 *
 * Проверки делятся на два класса:
 *   A) внутренняя непротиворечивость импорта (длины, конечность чисел);
 *   B) контракты, на которых держатся заявленные политики — они закреплены
 *      значением с указанием источника в дереве игры. Если upstream их меняет,
 *      скрипт обязан упасть, а не «подстроиться».
 */
import { CAMPS, MOBS, NPCS, QUESTS } from '../game/src/sim/data';
import { ACTIONS, NUM_ACTIONS, obsSize } from '../game/src/sim/obs';
import {
  INTERACT_RANGE,
  MAX_LEVEL,
  MELEE_RANGE,
  PLAYER_INTEREST_DROP_RADIUS,
  RUN_SPEED,
} from '../game/src/sim/types';
import {
  allCamps,
  campsFor,
  gameFacts,
  INTEREST_DROP_RADIUS,
  mobLevelRange,
  mobsDropping,
  npcPins,
  questOrder,
} from '../src/facts';
import { objectiveTypeCounts } from '../src/world/quest_policy';

const fails: string[] = [];
function check(cond: boolean, msg: string): void {
  if (!cond) fails.push(msg);
}
function num(v: unknown): boolean {
  return typeof v === 'number' && Number.isFinite(v);
}

const facts = gameFacts();

// --- A) непротиворечивость импорта -------------------------------------------
check(obsSize() === facts.obsSize, `obsSize() = ${obsSize()}, а gameFacts().obsSize = ${facts.obsSize}`);
check(ACTIONS.length === NUM_ACTIONS, `ACTIONS.length = ${ACTIONS.length}, NUM_ACTIONS = ${NUM_ACTIONS}`);
check(questOrder.length === Object.keys(QUESTS).length, 'questOrder и QUESTS разной длины');
check(npcPins().length === Object.keys(NPCS).length, 'npcPins() и NPCS разной длины');
check(allCamps().length === CAMPS.length, 'allCamps() и CAMPS разной длины');
check(facts.meleeRange === MELEE_RANGE && facts.interactRange === INTERACT_RANGE, 'диапазоны атаки/взаимодействия разошлись');
check(facts.maxLevel === MAX_LEVEL, 'потолок уровня разошёлся');
for (const p of npcPins()) check(num(p.x) && num(p.z), `пин NPC ${p.templateId} без конечных координат`);
for (const c of allCamps()) check(num(c.x) && num(c.z) && num(c.radius), `лагерь ${c.mobId} без конечных координат`);

// --- B) контракты заявленных политик -----------------------------------------
// Наблюдение: VIEW_RADIUS=60 взят из RL-obs игры (obs.ts: d < 60).
check(facts.obsSize === 607, `obsSize=${facts.obsSize}, ожидали 607 (контракт RL-наблюдения, obs.ts)`);
check(NUM_ACTIONS === 61, `NUM_ACTIONS=${NUM_ACTIONS}, ожидали 61 (словарь ACTIONS)`);
// Радиус интереса живой игры — на нём стоит модель наблюдения (ONLINE-WORLD.md).
check(
  PLAYER_INTEREST_DROP_RADIUS === 100 && INTEREST_DROP_RADIUS === 100,
  `PLAYER_INTEREST_DROP_RADIUS=${PLAYER_INTEREST_DROP_RADIUS}, ожидали 100 (src/sim/types.ts:56)`,
);
// Скорости: побег пешком невозможен — на этом стоит политика боя/отхода.
const wolf = (MOBS as Record<string, { moveSpeed?: number }>).forest_wolf;
const boar = (MOBS as Record<string, { moveSpeed?: number }>).wild_boar;
check(num(RUN_SPEED) && RUN_SPEED === 7, `RUN_SPEED=${RUN_SPEED}, ожидали 7 (src/sim/types.ts:39)`);
check(!!wolf && (wolf.moveSpeed ?? 0) > RUN_SPEED, `forest_wolf.moveSpeed=${wolf?.moveSpeed} — должен превышать RUN_SPEED`);
check(!!boar && (boar.moveSpeed ?? 0) > RUN_SPEED, `wild_boar.moveSpeed=${boar?.moveSpeed} — должен превышать RUN_SPEED`);
// Уровневый вентиль: Old Greyjaw — 4 уровень, 110 HP (квест q_greyjaw).
const greyjaw = mobLevelRange('old_greyjaw');
check(greyjaw?.maxLevel === 4, `old_greyjaw.maxLevel=${greyjaw?.maxLevel}, ожидали 4 (контент зоны 1)`);
// Таблица лута: цель collect у q_greyjaw закрывается только с old_greyjaw.
check(
  mobsDropping('greyjaw_fang').includes('old_greyjaw'),
  `greyjaw_fang не падает с old_greyjaw: ${JSON.stringify(mobsDropping('greyjaw_fang'))}`,
);
check(campsFor('old_greyjaw').length > 0, 'у old_greyjaw нет лагеря в CAMPS — навигация по карте сломается');
// Цели квестов: непроходимые типы (gather/farm/escort) обязаны существовать,
// иначе наша политика «не брать» стала бы бессмысленной.
const counts = objectiveTypeCounts();
let totalObjectives = 0;
for (const qid of questOrder) totalObjectives += (QUESTS as Record<string, { objectives: unknown[] }>)[qid]?.objectives.length ?? 0;
check(
  Object.values(counts).reduce((a, b) => a + b, 0) === totalObjectives,
  'сумма типов целей не совпала с числом целей в QUESTS',
);
for (const t of ['kill', 'collect', 'interact', 'gather', 'farm', 'escort']) {
  check((counts[t] ?? 0) > 0, `тип цели "${t}" исчез из данных игры — политика квестов устарела`);
}

// --- отчёт --------------------------------------------------------------------
console.log('Факты игры (импорт из upstream, руки ничего не переписывают):');
console.log(`  obs=${facts.obsSize} actions=${facts.numActions} max_level=${facts.maxLevel} melee=${facts.meleeRange} interact=${facts.interactRange}`);
console.log(`  квестов=${questOrder.length} NPC=${npcPins().length} лагерей=${allCamps().length} мобов=${Object.keys(MOBS).length}`);
console.log(`  цели квестов: ${Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([t, n]) => `${t}=${n}`).join(', ')}`);
console.log(`  RUN_SPEED=${RUN_SPEED} forest_wolf=${wolf?.moveSpeed} wild_boar=${boar?.moveSpeed} interest_drop=${PLAYER_INTEREST_DROP_RADIUS}`);

if (fails.length > 0) {
  console.error('\nДерево игры разошлось с тем, на чём стоят политики агента:');
  for (const f of fails) console.error(`  - ${f}`);
  process.exit(1);
}
console.log('сверка фактов: OK');
