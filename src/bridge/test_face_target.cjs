// src/bridge/test_face_target.cjs — правило «смотреть на цель перед атакой».
// Пользователь 2026-08-24: «персонаж должен смотреть на цель чтобы атаковать».
// Замер до фикса: в case 10/11 (касты) доворота не было вовсе — только stop()
// и castAbility; в farm доворот делался лишь при |off| > 0.25.
// Run: node src/bridge/test_face_target.cjs
const assert = require('assert');
const { faceTargetPlan, FACE_EPS } = require('./heading.cjs');

let passed = 0;
function t(name, fn) {
  try { fn(); passed++; console.log('PASS', name); }
  catch (e) { console.error('FAIL', name, '-', e.message); process.exitCode = 1; }
}

t('нужен доворот, когда цель сбоку', () => {
  // игрок в [0,0] смотрит на +Z (facing 0), цель на востоке
  const plan = faceTargetPlan({ x: 0, z: 0 }, { x: 10, z: 0 }, 0);
  assert.strictEqual(plan.needFace, true);
  assert.ok(Math.abs(plan.desired - Math.PI / 2) < 1e-6, 'курс = atan2(dx,dz)');
});

t('доворот не нужен, когда уже смотрим на цель', () => {
  const plan = faceTargetPlan({ x: 0, z: 0 }, { x: 0, z: 10 }, 0);
  assert.strictEqual(plan.needFace, false);
  assert.ok(Math.abs(plan.off) <= FACE_EPS);
});

t('цель позади -> максимальный доворот', () => {
  const plan = faceTargetPlan({ x: 0, z: 0 }, { x: 0, z: -10 }, 0);
  assert.strictEqual(plan.needFace, true);
  assert.ok(Math.abs(plan.off) > 3.0, 'ошибка курса ~pi');
});

t('desired всегда нормализован в (-pi, pi]', () => {
  for (const [tx, tz] of [[5, 5], [-5, 5], [-5, -5], [5, -5]]) {
    const plan = faceTargetPlan({ x: 0, z: 0 }, { x: tx, z: tz }, 3.0);
    assert.ok(plan.desired > -Math.PI - 1e-9 && plan.desired <= Math.PI + 1e-9);
    assert.ok(plan.off > -Math.PI - 1e-9 && plan.off <= Math.PI + 1e-9);
  }
});

t('порог доворота строгий (атака требует точного курса)', () => {
  // 0.2 рад (~11°) уже должно требовать доворота: раньше farm пропускал это
  const plan = faceTargetPlan({ x: 0, z: 0 }, { x: 2, z: 10 }, 0);
  assert.ok(Math.abs(plan.off) > FACE_EPS, 'малое отклонение тоже доворачиваем');
  assert.strictEqual(plan.needFace, true);
});

t('FACE_EPS достаточно мал, чтобы атака попадала', () => {
  assert.ok(FACE_EPS <= 0.15, `FACE_EPS=${FACE_EPS} слишком велик для атаки`);
});

console.log('\n' + passed + ' tests passed');
