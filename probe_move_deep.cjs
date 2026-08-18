// Глубокий probe: почему delta~0? Проверяем состояние игрока, применение moveInput, скорость, коллизии.
const puppeteer = require('puppeteer-core');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://localhost:9222' });
  const pages = await browser.pages();
  const page = pages.find((p) => /worldofclaudecraft|game/i.test(p.url() || '')) || pages[0];
  if (!page) { console.error('no page'); process.exit(1); }
  await page.waitForFunction('window.__game && window.__game.sim && window.__game.sim.player', { timeout: 20000 });

  const diag = async (label) => {
    const d = await page.evaluate(() => {
      const g = window.__game, p = g.sim.player, e = g.sim.entities?.get?.(p.id);
      return {
        pos: { x: p.pos?.x, z: p.pos?.z },
        vel: e ? { vx: e.vel?.x, vz: e.vel?.z, speed: Math.hypot(e.vel?.x||0, e.vel?.z||0) } : 'no entity',
        moveInput: JSON.stringify(g.sim.moveInput),
        onlineMoveInput: g.online ? JSON.stringify(g.online.moveInput) : 'n/a',
        inputEnabled: g.input?.enabled,
        suspend: g.input?.suspendMovement,
        gate: g.input?.gameplayInputGate,
        onlineGate: g.online?.inputGate,
        hook: g.input?.hookType,
        state: p.state,
        onGround: e?.onGround,
        stuck: e?.stuck,
        alive: !p.dead,
      };
    });
    console.log(label, JSON.stringify(d));
  };

  await diag('BEFORE');
  // пробуем online.setMoveInput на 5 секунд
  await page.evaluate(() => window.__game.online.setMoveInput({ forward: 1 }));
  await sleep(500); await diag('t=0.5s');
  await sleep(2000); await diag('t=2.5s');
  await sleep(2500); await diag('t=5s');
  // стоп
  await page.evaluate(() => window.__game.online.setMoveInput({}));
  await sleep(500); await diag('AFTER STOP');

  // теперь controller.setMoveInput на 5 сек
  await page.evaluate(() => window.__game.controller?.setMoveInput?.({ forward: 1 }));
  await sleep(500); await diag('ctrl t=0.5s');
  await sleep(4000); await diag('ctrl t=4.5s');
  await page.evaluate(() => { try{window.__game.controller?.setMoveInput?.({});}catch{}; try{window.__game.online.setMoveInput({});}catch{} });

  await browser.disconnect();
  console.log('DONE');
})().catch((e) => { console.error('ERR', e); process.exit(1); });
