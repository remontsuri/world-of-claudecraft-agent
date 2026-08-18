// _click_play.cjs — click "Играть" on the WoC login screen, then wait for the sim
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('claudecraft')) { page = p; break; }
  }
  if (!page) { console.error('no game tab'); process.exit(2); }
  await page.bringToFront();
  // click the "Играть" button
  const clicked = await page.evaluate(() => {
    const els = [...document.querySelectorAll('button, a, [role=button]')];
    const btn = els.find(e => /играть/i.test(e.textContent || ''));
    if (btn) { btn.click(); return true; }
    return false;
  });
  console.log('clicked Играть:', clicked);
  // wait for sim to come alive
  try {
    await page.waitForFunction('!!(window.__game && window.__game.sim && window.__game.sim.player)', { timeout: 60000 });
    console.log('sim ready');
  } catch (e) { console.error('sim timeout:', e.message); }
  await new Promise(r => setTimeout(r, 2000));
  const pos = await page.evaluate(() => {
    try { return [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z)]; }
    catch (e) { return null; }
  }).catch(() => null);
  console.log('pos after login:', pos);
  await browser.disconnect();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
