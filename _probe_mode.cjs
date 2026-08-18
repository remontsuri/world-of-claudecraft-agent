
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.log('NO GAME TAB'); await browser.disconnect(); return; }
  await page.bringToFront();
  try { await page.waitForFunction('!!window.__game && !!window.__game.sim && !!window.__game.sim.player', { timeout: 30000 }); }
  catch(e){ console.log('WAIT TIMEOUT'); await browser.disconnect(); return; }

  const meta = await page.evaluate(() => {
    const g = window.__game, sim = g.sim;
    return {
      mode: g.mode,
      hasOnline: !!g.online,
      account: g.account ? g.account.username : null,
      simPaused: sim.paused ?? null,
      simRunning: sim.running ?? null,
      isConnected: g.online ? g.online.connected ?? g.online.isConnected ?? 'unknown' : 'no-online',
      playerDead: !!sim.player.dead,
      tabVisible: (typeof document !== 'undefined') ? document.visibilityState : 'unknown',
      documentHidden: (typeof document !== 'undefined') ? document.hidden : 'unknown',
    };
  });

  // try autostart-style movement: hold forward across simulated ticks via repeated rAF-ish await
  const before = await page.evaluate(() => [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z)]);
  await page.evaluate(async () => {
    const g = window.__game;
    try { g.controller.stop(); } catch(_){}
    for (let i=0;i<10;i++){ try { g.controller.move({ forward: true }); } catch(_){}; await new Promise(r=>setTimeout(r,150)); }
  });
  const after = await page.evaluate(() => [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z)]);
  // try startAutoRun path
  let autoTried=false, autoErr=null;
  try { await page.evaluate(() => { if (window.__game.sim.startAutoRun) window.__game.sim.startAutoRun(); }); autoTried=true; } catch(e){ autoErr=e.message; }
  await new Promise(r=>setTimeout(r,1000));
  const afterAuto = await page.evaluate(() => [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z)]);

  console.log(JSON.stringify({ meta, before, afterHeld: after, movedHeld: before[0]!==after[0]||before[1]!==after[1], autoTried, autoErr, afterAuto, movedAuto: before[0]!==afterAuto[0]||before[1]!==afterAuto[1] }, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
