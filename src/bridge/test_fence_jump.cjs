// src/bridge/test_fence_jump.cjs
// КОРНЕВАЯ ПРИЧИНА (найдена по правилам игры 2026-08-24, systematic-debugging):
//   src/sim/player_motion.ts:432  const clearFences = !p.onGround && p.jumping;
//   src/sim/colliders.ts:1735     if (ignoreFences && c.isFence) continue;
// Забор проходится ТОЛЬКО в прыжке. Рабочий пример — клик-мышью
// (src/main.ts:3959-3965): каждый кадр проверяет pathCrossesFence(pos, ahead)
// и ставит mi.jump = true.
// Наш навигатор (actions.cjs) слова "jump" не содержал вовсе: при застревании
// он поворачивал на 120° и толкался, то есть шёл ВДОЛЬ забора, никогда его не
// преодолевая. Отсюда «упёрся в забор» и позиция, не меняющаяся десятки шагов.
// Run: node src/bridge/test_fence_jump.cjs
const assert = require('assert');
const { fenceHopPlan, FENCE_LOOKAHEAD } = require('./fence_hop.cjs');

let passed = 0;
function t(name, fn) {
  try { fn(); passed++; console.log('PASS', name); }
  catch (e) { console.error('FAIL', name, '-', e.message); process.exitCode = 1; }
}

t('точка впереди считается по курсу (как клик-мышью в main.ts)', () => {
  // facing 0 -> +Z; точка впереди должна лежать на FENCE_LOOKAHEAD по Z
  const ahead = fenceHopPlan({ x: 10, z: 20 }, 0, false, false).ahead;
  assert.ok(Math.abs(ahead.x - 10) < 1e-6, `ahead.x=${ahead.x}`);
  assert.ok(Math.abs(ahead.z - (20 + FENCE_LOOKAHEAD)) < 1e-6, `ahead.z=${ahead.z}`);
});

t('забор впереди на земле -> прыгаем', () => {
  const plan = fenceHopPlan({ x: 0, z: 0 }, 0, true /*fenceAhead*/, true /*onGround*/);
  assert.strictEqual(plan.jump, true, 'должны поставить jump');
});

t('забора нет -> не прыгаем впустую', () => {
  const plan = fenceHopPlan({ x: 0, z: 0 }, 0, false, true);
  assert.strictEqual(plan.jump, false);
});

t('уже в воздухе -> не дублируем прыжок (сим прыгает только с земли)', () => {
  const plan = fenceHopPlan({ x: 0, z: 0 }, 0, true, false /*onGround=false*/);
  assert.strictEqual(plan.jump, false,
    'sim: inp.jump && (p.onGround || coyote) — в воздухе бесполезно');
});

t('lookahead положительный и небольшой', () => {
  assert.ok(FENCE_LOOKAHEAD > 0 && FENCE_LOOKAHEAD <= 3,
    `FENCE_LOOKAHEAD=${FENCE_LOOKAHEAD} должен быть 0..3 yd`);
});

t('план всегда содержит forward (прыжок в движении, не на месте)', () => {
  const plan = fenceHopPlan({ x: 0, z: 0 }, 1.0, true, true);
  assert.strictEqual(plan.forward, true);
});

t('курс под углом: ahead считается через sin/cos правильно', () => {
  const f = Math.PI / 2;                    // смотрим на +X
  const ahead = fenceHopPlan({ x: 0, z: 0 }, f, false, false).ahead;
  assert.ok(Math.abs(ahead.x - FENCE_LOOKAHEAD) < 1e-6, `ahead.x=${ahead.x}`);
  assert.ok(Math.abs(ahead.z) < 1e-6, `ahead.z=${ahead.z}`);
});

console.log('\n' + passed + ' tests passed');
