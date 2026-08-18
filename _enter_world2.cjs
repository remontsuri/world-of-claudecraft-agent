// _enter_world2.cjs — enter WoC world on a fresh tab: click Играть, then Перехватить, wait sim
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('claudecraft')) { page = p; break; }
  }
  if (!page) { console.error('no game tab'); process.exit(2); }
  await page.bringToFront();
  await sleep(1500);
  // Step 1: Играть
  let ok = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button, a, [role=button]')].find(e => /играть/i.test(e.textContent || ''));
    if (b) { b.click(); return true; } return false;
  });
  console.log('clicked Играть:', ok);
  await sleep(2500);
  // Step 2: Перехватить on REMONTSURI card
  ok = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('*')].filter(el => /remontsuri/i.test(el.textContent || '') && el.children.length < 8);
    for (const el of cards) {
      const btn = [...el.querySelectorAll('button')].find(b => /перехватить/i.test(b.textContent || ''));
      if (btn) { btn.click(); return true; }
    }
    const any = [...document.querySelectorAll('button')].find(b => /перехватить/i.test(b.textContent || ''));
    if (any) { any.click(); return true; }
    return false;
  });
  console.log('clicked Перехватить:', ok);
  // wait for sim
  try {
    await page.waitForFunction('!!(window.__game && window.__game.sim && window.__game.sim.player)', { timeout: 60000 });
    console.log('sim ready');
  } catch (e) { console.error('sim timeout:', e.message); }
  await sleep(2500);
  const info = await page.evaluate(() => {
    try {
      const p = window.__game.sim.player;
      return { pos: [Math.round(p.pos.x), Math.round(p.pos.z)], hp: p.hp };
    } catch (e) { return { err: e.message }; }
  }).catch(e => ({ err: e.message }));
  console.log('in-world:', JSON.stringify(info));
  await browser.disconnect();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
