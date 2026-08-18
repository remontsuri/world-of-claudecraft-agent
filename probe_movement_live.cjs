// Live movement-path probe: проверяет КАКОЙ путь реально двигает агента
// в текущем рантайме. Не предполагаем — измеряем delta.
// Запуск: node probe_movement_live.cjs
const puppeteer = require('puppeteer-core');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://localhost:9222' });
  const pages = await browser.pages();
  const page = pages.find((p) => /worldofclaudecraft|game/i.test(p.url() || '')) || pages[0];
  if (!page) { console.error('no page'); process.exit(1); }

  // дождаться __game
  await page.waitForFunction('window.__game && window.__game.sim && window.__game.sim.player', { timeout: 20000 });

  const readPos = () => page.evaluate(() => {
    const p = window.__game.sim.player;
    return { x: p.pos?.x, z: p.pos?.z, facing: p.facing };
  });

  const probe = async (label, fn, holdMs = 2000) => {
    const before = await readPos();
    await page.evaluate(fn);
    await sleep(holdMs);
    const after = await readPos();
    const d = Math.hypot((after.x ?? 0) - (before.x ?? 0), (after.z ?? 0) - (before.z ?? 0));
    console.log(`${label}: before(${before.x?.toFixed(2)},${before.z?.toFixed(2)}) after(${after.x?.toFixed(2)},${after.z?.toFixed(2)}) delta=${d.toFixed(2)}`);
    // stop
    await page.evaluate(() => { try { window.__game.online.setMoveInput({}); } catch {} try { window.__game.controller?.setMoveInput?.({}); } catch {} try { window.__game.sim.moveInput = {}; } catch {} });
    await sleep(500);
    return d;
  };

  // gate state
  const gate = await page.evaluate(() => {
    const g = window.__game;
    const out = {};
    try { out.inputSuspend = g.input?.suspendMovement; } catch {}
    try { out.gameplayGate = g.input?.gameplayInputGate; } catch {}
    try { out.onlineGate = g.online?.inputGate; } catch {}
    try { out.moveInput = JSON.stringify(g.sim.moveInput); } catch {}
    return out;
  });
  console.log('GATE:', JSON.stringify(gate));

  await probe('online.setMoveInput', () => { window.__game.online.setMoveInput({ forward: 1 }); });
  await probe('controller.setMoveInput', () => { window.__game.controller?.setMoveInput?.({ forward: 1 }); });
  await probe('sim.moveInput+gateskip', () => {
    // принудительно снять gate как в bridge_online
    try { window.__game.input.suspendMovement = false; } catch {}
    try { window.__game.input.gameplayInputGate = false; } catch {}
    window.__game.sim.moveInput = { forward: 1 };
  });
  await probe('online.setMoveInput after gate-skip', () => {
    try { window.__game.input.suspendMovement = false; } catch {}
    try { window.__game.input.gameplayInputGate = false; } catch {}
    window.__game.online.setMoveInput({ forward: 1 });
  });

  await browser.disconnect();
  console.log('DONE');
})().catch((e) => { console.error('ERR', e); process.exit(1); });
