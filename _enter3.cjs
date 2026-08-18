// _enter3.cjs — click Играть once, then wait long for the game bundle to load
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
  const ok = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button, a, [role=button]')].find(e => /играть/i.test(e.textContent || ''));
    if (b) { b.click(); return true; } return false;
  });
  console.log('clicked Играть:', ok);
  // game bundle can take 30-60s to load
  let ready = false;
  for (let i = 0; i < 12; i++) {
    await sleep(5000);
    ready = await page.evaluate(() => !!(window.__game && window.__game.sim && window.__game.sim.player)).catch(() => false);
    if (ready) { console.log('sim ready after', (i + 1) * 5, 's'); break; }
    console.log(`  ...waiting ${((i + 1) * 5)}s, sim=${ready}`);
  }
  if (ready) {
    const info = await page.evaluate(() => {
      const p = window.__game.sim.player;
      return { pos: [Math.round(p.pos.x), Math.round(p.pos.z)], hp: p.hp };
    }).catch(e => ({ err: e.message }));
    console.log('in-world:', JSON.stringify(info));
  } else {
    console.log('still no sim — dumping page state');
    const dbg = await page.evaluate(() => ({
      hasGame: !!window.__game,
      url: location.href,
      bodyText: (document.body.innerText || '').slice(0, 200),
    })).catch(e => ({ err: e.message }));
    console.log(JSON.stringify(dbg));
  }
  await browser.disconnect();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
