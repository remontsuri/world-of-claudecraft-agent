// test_buy_vendor_range.cjs — regression: buy НЕ вызывается у дальнего вендора.
// Сценарий (review f1ce454): vendor 100 yd -> sim.buyItem НЕ зовётся,
// возвращается {far} -> navigateToCoord -> повторная попытка у вендора.
const fs = require('fs');
const src = fs.readFileSync('D:/world-of-claudecraft/src/bridge/actions.cjs', 'utf-8');

// Берём тело case 9 (buy)
const m = src.match(/case 9:[\s\S]*?\n      break;/);
if (!m) { console.error('FAIL: case 9 не найден'); process.exit(1); }
const body = m[0];

// 1. Дистанция проверяется ДО sim.buyItem (ищем ВЫЗОВ, не упоминание в комментарии)
const callPos = body.indexOf('try { sim.buyItem');
const farPos = body.indexOf("bd > 5");
if (callPos < 0) { console.error('FAIL: вызов sim.buyItem не найден'); process.exit(1); }
if (farPos < 0) { console.error('FAIL: проверка дистанции bd > 5 отсутствует'); process.exit(1); }
if (callPos < farPos) {
  console.error('FAIL: sim.buyItem вызывается ДО проверки дистанции — покупка у дальнего вендора всё ещё возможна');
  process.exit(1);
}

// 2. far-ветка существует и ведёт к navigateToCoord
if (!/far:\s*true/.test(body)) { console.error('FAIL: нет far-ветки'); process.exit(1); }
if (!body.includes('navigateToCoord')) { console.error('FAIL: нет навигации к вендору'); process.exit(1); }

// 3. none -> честный noTarget для верификатора
if (!/gatherNoTarget = true/.test(body)) { console.error('FAIL: нет honest noTarget'); process.exit(1); }

console.log('PASS: buy вызывает sim.buyItem только в interaction range, иначе navigate');
