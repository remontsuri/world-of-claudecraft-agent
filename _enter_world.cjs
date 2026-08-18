// _enter_world.cjs — click "Перехватить" on REMONTSURI char card, wait for sim
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
  const clicked = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('*')].filter(el => /remontsuri/i.test(el.textContent || '') && el.children.length < 6);
    // find the char card container, then the "Перехватить" button inside it
    for (const el of cards) {
      const btn = [...el.querySelectorAll('button')].find(b => /перехватить/i.test(b.textContent || ''));
      if (btn) { btn.click(); return true; }
    }
    // fallback: any button with text Перехватить
    const any = [...document.querySelectorAll('button')].find(b => /перехватить/i.test(b.textContent || ''));
    if (any) { any.click(); return true; }
    return false;
  });
  console.log('clicked Перехватить:', clicked);
  try {
    await page.waitForFunction('!!(window.__game && window.__game.sim && window.__game.sim.player)', { timeout: 60000 });
    console.log('sim ready');
  } catch (e) { console.error('sim timeout:', e.message); }
  await new Promise(r => setTimeout(r, 2500));
  const pos = await page.evaluate(() => {
    try { return [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z), window.__game.sim.player.hp]; }
    catch (e) { return null; }
  }).catch(() => null);
  console.log('pos/hp after enter:', pos);
  await browser.disconnect();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
