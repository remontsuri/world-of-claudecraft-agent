// probe_movement_analysis.cjs — ТОЛЬКО анализ (без правок моста/адаптера).
// Снимает реальный input-API в текущем рантайме и измеряет, какой путь двигает.
// disconnect() — не закрывает браузер.
const puppeteer = require('puppeteer-core');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://localhost:9222' });
  const pages = await browser.pages();
  const page = pages.find((p) => /claudecraft/i.test(p.url() || '')) || pages[0];
  await page.waitForFunction('window.__game && window.__game.sim && window.__game.sim.player', { timeout: 15000 });

  // 1. ПЕРЕЧЕНЬ API
  const api = await page.evaluate(() => {
    const g = window.__game;
    const fns = (o) => o ? Object.keys(o).filter((k) => typeof o[k] === 'function') : [];
    const has = (o, k) => o && typeof o[k] === 'function';
    return {
      online_fns: fns(g.online),
      controller_fns: fns(g.controller),
      input_fns: fns(g.input),
      sim_moveInput_keys: g.sim.moveInput ? Object.keys(g.sim.moveInput) : 'none',
      online_has_setMoveInput: has(g.online, 'setMoveInput'),
      online_has_move: has(g.online, 'move'),
      controller_has_setMoveInput: has(g.controller, 'setMoveInput'),
      controller_has_move: has(g.controller, 'move'),
      controller_has_face: has(g.controller, 'face'),
      input_has_setMoveInput: has(g.input, 'setMoveInput'),
      input_enabled: g.input?.enabled,
      input_suspend: g.input?.suspendMovement,
      input_gate: g.input?.gameplayInputGate,
      online_gate: g.online?.inputGate,
      online_moveInput: g.online ? JSON.stringify(g.online.moveInput) : 'n/a',
      sim_moveInput: JSON.stringify(g.sim.moveInput),
    };
  });
  console.log('=== API INVENTORY ===');
  console.log(JSON.stringify(api, null, 1));

  // 2. ИЗМЕРЕНИЕ DELTA для каждого кандидата (по 1.5с, потом стоп)
  const measure = async (label, fn) => {
    const before = await page.evaluate(() => { const p = window.__game.sim.player; return { x: p.pos.x, z: p.pos.z }; });
    await page.evaluate(fn);
    await sleep(1500);
    const after = await page.evaluate(() => { const p = window.__game.sim.player; return { x: p.pos.x, z: p.pos.z }; });
    const d = Math.hypot(after.x - before.x, after.z - before.z);
    // стоп
    await page.evaluate(() => { try { window.__game.online.setMoveInput({}); } catch {} try { window.__game.controller?.setMoveInput?.({}); } catch {} try { window.__game.sim.moveInput = {}; } catch {} });
    await sleep(400);
    console.log(`${label}: delta=${d.toFixed(2)} (before ${before.x.toFixed(1)},${before.z.toFixed(1)} -> ${after.x.toFixed(1)},${after.z.toFixed(1)})`);
    return d;
  };

  console.log('=== DELTA MEASUREMENTS ===');
  await measure('A online.setMoveInput({forward:1})', () => window.__game.online.setMoveInput({ forward: 1 }));
  await measure('B sim.moveInput={forward:1} (прямо)', () => { window.__game.sim.moveInput = { forward: 1 }; });
  await measure('C online.move({forward:true})', () => window.__game.online.move?.({ forward: true }));
  await measure('D controller.move({forward:true})', () => window.__game.controller?.move?.({ forward: true }));
  await measure('E input.setMoveInput({forward:1})', () => window.__game.input?.setMoveInput?.({ forward: 1 }));

  // 3. СОСТОЯНИЕ ПОСЛЕ ПОПЫТКИ A (online.setMoveInput) — применился ли moveInput?
  const postA = await page.evaluate(() => ({
    sim_moveInput: JSON.stringify(window.__game.sim.moveInput),
    online_moveInput: window.__game.online ? JSON.stringify(window.__game.online.moveInput) : 'n/a',
  }));
  console.log('=== POST-A STATE ===');
  console.log(JSON.stringify(postA));

  await browser.disconnect();
  console.log('DONE (browser left running)');
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
