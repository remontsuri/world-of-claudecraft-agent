const fs = require('fs');
const src = fs.readFileSync('D:/world-of-claudecraft/src/bridge/actions.cjs', 'utf-8');
const navMatch = src.match(/async function navigateToCoord[\s\S]*?^}/m);
if (!navMatch) { console.error('FAIL: navigateToCoord не найдена'); process.exit(1); }
if (!/await sleep\(gameClient\.tickMs\)/.test(navMatch[0])) {
  console.error('FAIL: navigateToCoord не ждёт tick между итерациями');
  process.exit(1);
}
console.log('PASS: navigateToCoord ждёт tick');
