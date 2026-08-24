// Fix6 regression: navigateToCoord's anti-stuck ladder must include a JUMP push
// (fences are hoppable rails) and a BACK-off before the zigzag. Asserts on the
// evaluate payloads the bridge sends (string markers), per test_bridge.cjs mock style.
const assert = require('assert');
const { createActions } = require('./actions.cjs');

(async () => {
  const evalBodies = [];
  const gc = {
    tickMs: 0,
    evaluate(fn, ...args) {
      try { evalBodies.push(String(fn)); } catch (_) {}
      return Promise.resolve({ arrived: false, d: 30, x: 0, z: 0 });
    },
  };
  const a = createActions({
    gameClient: gc,
    buildSnapshot: async () => ({ pos: [0, 0] }),
    tickMs: 0,
  });
  await a.navigate({ x: 50, z: 50, max_steps: 40 });

  const all = evalBodies.join('\n');
  assert(all.length > 0, 'navigate issued no evaluate calls');
  assert(/jump:\s*true/.test(all),
    'stuck ladder must send controller.move({forward,jump}) — fences are hoppable');
  assert(/back:\s*true/.test(all),
    'stuck ladder must include a back:true retreat step before zigzag');
  console.log('Fix6 tests PASSED (jump + back present in stuck ladder)');
})().catch((e) => { console.error('FAIL:', e.message); process.exit(1); });
