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
import gamePkg from '../game/package.json';
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

/** Версия игры, на которой измерены эталоны приёмки и контракты ниже.
 *  Совпадает с GAME_EXPECTED_VERSION в tools/setup_game.sh и -ExpectedVersion в
 *  tools/fix_windows_env.ps1. Переезд на другую версию — отдельная задача (ROADMAP A5). */
const EXPECTED_GAME_VERSION = '0.43.2';
const gameVersion = String((gamePkg as { version?: unknown }).version ?? '?');

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

// --- C) чистота дерева игры (факты — из ИСХОДНИКОВ upstream, не из сборки) ------
// В upstream levy-street/world-of-claudecraft в src/sim и headless НЕТ .js-файлов:
// там 793 .ts и 0 .js (проверено на чистом sparse-клоне 2026-09-18). Если .js
// появились — это собранный вывод (tsc/esbuild/релизный dist), и он опасен вдвойне:
//   1) Vite/vitest резолвит .js РАНЬШЕ .ts, поэтому факты молча берутся из устаревшей
//      сборки, а не из исходников (сборка esbuild при этом зелёная — у него .ts раньше);
//   2) игра объявляет "type": "module", а собранный .js часто CJS → на чужом дереве
//      это «ReferenceError: exports is not defined in ES module scope» в тестах.
// Лечится не алиасами на копию дерева, а очисткой дерева игры.
{
  const { existsSync, readdirSync, statSync } = await import('node:fs');
  const { dirname, join, resolve } = await import('node:path');
  const { fileURLToPath } = await import('node:url');

  // Бандл лежит в dist/, исходник в tools/ — ищем корень проекта вверх по дереву.
  let root = dirname(fileURLToPath(import.meta.url));
  for (let i = 0; i < 6 && !existsSync(join(root, 'game', 'src', 'sim', 'obs.ts')); i++) {
    root = dirname(root);
  }
  const gameDir = resolve(root, 'game');
  check(existsSync(join(gameDir, 'src', 'sim', 'obs.ts')), `в дереве игры нет src/sim/obs.ts: ${gameDir} — нужен клон ИСХОДНИКОВ upstream (bash tools/setup_game.sh)`);
  check(existsSync(join(gameDir, 'src', 'sim', 'data.ts')), `в дереве игры нет src/sim/data.ts: ${gameDir}`);

  const stray: string[] = [];
  const scan = (dir: string, depth: number): void => {
    if (depth > 4 || !existsSync(dir)) return;
    for (const e of readdirSync(dir)) {
      if (e === 'node_modules') continue;
      const full = join(dir, e);
      let st;
      try { st = statSync(full); } catch { continue; }
      if (st.isDirectory()) scan(full, depth + 1);
      else if (/\.(js|cjs|mjs)$/.test(e)) stray.push(full.slice(gameDir.length + 1));
    }
  };
  scan(join(gameDir, 'src', 'sim'), 0);
  scan(join(gameDir, 'headless'), 0);
  check(
    stray.length === 0,
    `дерево игры загрязнено собранным выводом: ${stray.length} файл(ов) .js/.cjs/.mjs в src/sim и headless`
      + ` (например: ${stray.slice(0, 3).join(', ')}). В upstream там только .ts.`
      + ` Удалите сборку из дерева игры (git clean -xd в D:\\woc-game или свежий клон) —`
      + ` иначе vitest берёт факты из .js вместо .ts. Копии дерева с переименованием`
      + ` .js→.cjs и алиасы на них — не решение: факты обязаны браться из исходников upstream.`,
  );
}

// --- отчёт --------------------------------------------------------------------
console.log(`Факты игры (импорт из upstream v${gameVersion}, руки ничего не переписывают):`);
console.log(`  obs=${facts.obsSize} actions=${facts.numActions} max_level=${facts.maxLevel} melee=${facts.meleeRange} interact=${facts.interactRange}`);
console.log(`  квестов=${questOrder.length} NPC=${npcPins().length} лагерей=${allCamps().length} мобов=${Object.keys(MOBS).length}`);
console.log(`  цели квестов: ${Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([t, n]) => `${t}=${n}`).join(', ')}`);
console.log(`  RUN_SPEED=${RUN_SPEED} forest_wolf=${wolf?.moveSpeed} wild_boar=${boar?.moveSpeed} interest_drop=${PLAYER_INTEREST_DROP_RADIUS}`);

if (fails.length > 0) {
  console.error('\nДерево игры разошлось с тем, на чём стоят политики агента:');
  console.error(`  дерево игры: версия ${gameVersion} (контракты линии измерены на ${EXPECTED_GAME_VERSION})`);
  for (const f of fails) console.error(`  - ${f}`);
  if (gameVersion !== EXPECTED_GAME_VERSION) {
    console.error(`\nПЕРВОЕ, что проверить: версия дерева игры ${gameVersion} != ${EXPECTED_GAME_VERSION}.`);
    console.error('  Расхождение контрактов в этом случае означает НЕ «upstream уехал вперёд»,');
    console.error('  а «дерево игры другое» — чаще старое (на v0.41.x obs=593 и нет цели "farm")');
    console.error('  или неполное (data.ts тянет 56 модулей из src/sim/content/**, где 92 файла;');
    console.error('  obs = 16 + 96 + 9 + 30 + 5 + 2·число_квестов + 3, то есть 607 при 224 квестах,');
    console.error('  593 при 217 и 587 при 214 — по obs видно, сколько квестов не доехало).');
    console.error('  Привести дерево к pinned-версии:');
    console.error('    git -C <дерево игры> fetch --tags && git -C <дерево игры> checkout v' + EXPECTED_GAME_VERSION);
    console.error('    git -C <дерево игры> clean -xd src headless     # убрать собранный вывод, если есть');
    console.error('  или переклонировать: bash tools/setup_game.sh (GAME_REF=v' + EXPECTED_GAME_VERSION + ')');
    console.error('  Осознанный переезд на другую версию игры — задача ROADMAP A5: пересчитать');
    console.error('  контракты ниже и заново измерить эталоны прогонов, а не «подстроиться» молча.');
  }
  process.exit(1);
}
console.log('сверка фактов: OK');
