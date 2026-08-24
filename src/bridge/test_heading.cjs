// src/bridge/test_heading.cjs — тесты анти-рыскания (баг «камера дёргается»).
// Run: node src/bridge/test_heading.cjs
const assert = require('assert');
const { decideTurn, normalizeAngle, TURN_START, TURN_STOP } = require('./heading.cjs');

let passed = 0;
function t(name, fn) {
  try { fn(); passed++; console.log('PASS', name); }
  catch (e) { console.error('FAIL', name, '-', e.message); process.exitCode = 1; }
}

t('идём прямо когда курс точен', () => {
  const d = decideTurn(0.02, false);
  assert.strictEqual(d.forward, true);
  assert.strictEqual(d.turnLeft, false);
  assert.strictEqual(d.turnRight, false);
  assert.strictEqual(d.turning, false);
});

t('положительная ошибка -> turnLeft', () => {
  const d = decideTurn(0.6, false);
  assert.strictEqual(d.turnLeft, true);
  assert.strictEqual(d.turnRight, false);
});

t('отрицательная ошибка -> turnRight', () => {
  const d = decideTurn(-0.6, false);
  assert.strictEqual(d.turnRight, true);
  assert.strictEqual(d.turnLeft, false);
});

t('ГИСТЕРЕЗИС: между порогами не начинаем поворот с нуля', () => {
  // 0.2 рад: больше TURN_STOP(0.1), меньше TURN_START(0.35)
  const cold = decideTurn(0.2, false);
  assert.strictEqual(cold.turning, false, 'не должны начинать поворот');
  assert.strictEqual(cold.forward, true);
});

t('ГИСТЕРЕЗИС: начатый поворот доводим до малой ошибки', () => {
  const hot = decideTurn(0.2, true);
  assert.strictEqual(hot.turning, true, 'начатый поворот продолжается');
  assert.strictEqual(hot.turnLeft, true);
});

t('РЫСКАНИЕ НЕВОЗМОЖНО: знак не меняется каждый тик у порога', () => {
  // Имитируем перелёт через нуль на маленьких ошибках вокруг старого порога 0.2.
  // Со старой логикой (единый порог 0.2) знак дёргался каждый тик; с гистерезисом
  // мы либо идём прямо, либо доводим один поворот.
  const seq = [0.21, -0.19, 0.22, -0.18, 0.20, -0.21];
  let turning = false;
  let flips = 0, prevDir = null;
  for (const off of seq) {
    const d = decideTurn(off, turning);
    turning = d.turning;
    if (d.turning) {
      const dir = d.turnLeft ? 'L' : 'R';
      if (prevDir && dir !== prevDir) flips++;
      prevDir = dir;
    }
  }
  assert.ok(flips <= 1, `слишком много смен направления: ${flips}`);
});

t('крутой доворот делается БЕЗ forward (не орбитируем цель)', () => {
  const d = decideTurn(2.0, false);
  assert.strictEqual(d.turning, true);
  assert.strictEqual(d.forward, false, 'при большой ошибке идти вперёд нельзя');
});

t('умеренный поворот идёт вместе с forward', () => {
  const d = decideTurn(0.5, false);
  assert.strictEqual(d.turning, true);
  assert.strictEqual(d.forward, true);
});

t('normalizeAngle сворачивает угол в (-pi, pi]', () => {
  assert.ok(Math.abs(normalizeAngle(3 * Math.PI) - Math.PI) < 1e-9);
  assert.ok(Math.abs(normalizeAngle(-3 * Math.PI) - Math.PI) < 1e-9);
  assert.ok(Math.abs(normalizeAngle(0.5) - 0.5) < 1e-9);
});

t('пороги упорядочены: STOP < START (иначе гистерезиса нет)', () => {
  assert.ok(TURN_STOP < TURN_START);
});

console.log('\n' + passed + ' tests passed');
