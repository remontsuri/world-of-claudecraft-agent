// _reload_tab.cjs — reload the WoC game tab and wait for it to be playable again
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.error('no game tab'); process.exit(2); }
  const before = await page.evaluate(() => [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z)]).catch(()=>null);
  console.log('pos before reload:', before);
  await page.reload({ waitUntil: 'domcontentloaded' });
  // wait for the game sim to come back
  try {
    await page.waitForFunction('!!(window.__game && window.__game.sim && window.__game.sim.player)', { timeout: 60000 });
  } catch (e) { console.error('sim did not reappear:', e.message); }
  await new Promise(r => setTimeout(r, 3000));
  const after = await page.evaluate(() => [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z)]).catch(()=>null);
  console.log('pos after reload:', after);
  await browser.disconnect();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
