// Direct CDP probe (bypass the bridge) — does window.__game.controller.move
// actually change sim.player.pos? Pure fact, no bridge involved.
const { connect } = require('puppeteer-core');

(async () => {
  const browser = await connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await browser.pages();
  let page = pages.find(p => (p.url()||'').includes('worldofclaudecraft'));
  if (!page) { console.log('NO GAME TAB'); process.exit(1); }
  await page.bringToFront().catch(()=>{});

  const before = await page.evaluate(() => {
    const p = window.__game.sim.player;
    return { x: p.pos.x, z: p.pos.z, hasController: !!window.__game.controller,
             moveType: window.__game.controller && typeof window.__game.controller.move };
  });
  console.log('BEFORE', JSON.stringify(before));

  // try the move the bridge uses
  const r1 = await page.evaluate(() => {
    try { window.__game.controller.stop(); } catch(e){}
    window.__game.controller.move({ forward: true });
    return 'move-called';
  });
  await new Promise(r => setTimeout(r, 1500));
  const after = await page.evaluate(() => {
    const p = window.__game.sim.player;
    return { x: p.pos.x, z: p.pos.z };
  });
  console.log('AFTER', JSON.stringify(after));
  console.log('MOVED', before.x !== after.x || before.z !== after.z);
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
