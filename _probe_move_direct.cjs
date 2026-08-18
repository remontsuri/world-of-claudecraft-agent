
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

  const before = await page.evaluate(() => { const p = window.__game.sim.player; return [Math.round(p.pos.x), Math.round(p.pos.z)]; });
  // Attempt direct controller move (same call the bridge uses)
  await page.evaluate(() => { try { window.__game.controller.stop(); } catch(_){}; try { window.__game.controller.move({ forward: true }); } catch(_){}; });
  await new Promise(r => setTimeout(r, 1500));
  const after = await page.evaluate(() => { const p = window.__game.sim.player; return [Math.round(p.pos.x), Math.round(p.pos.z)]; });
  // Also report whether controller exists and its type
  const cinfo = await page.evaluate(() => {
    const c = window.__game && window.__game.controller;
    return { hasController: !!c, keys: c ? Object.keys(c).slice(0,20) : [], mode: window.__game && window.__game.mode };
  });
  console.log(JSON.stringify({ before, after, moved: before[0]!==after[0]||before[1]!==after[1], cinfo }, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
