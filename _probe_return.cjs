// _probe_return.cjs — find any "get me back to land / graveyard / hearth" API
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
  const out = await page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    const methods = [];
    for (const k of Object.getOwnPropertyNames(Object.getPrototypeOf(sim))) {
      if (/teleport|return|respawn|grave|hearth|revive|spawn|home|reset|port/i.test(k)) methods.push(k);
    }
    const pmethods = [];
    for (const k of Object.getOwnPropertyNames(Object.getPrototypeOf(p))) {
      if (/teleport|return|respawn|grave|hearth|revive|spawn|home|reset|port|swim|water|ground/i.test(k)) pmethods.push(k);
    }
    return {
      simMethods: methods,
      playerMethods: pmethods,
      haveReleaseSpirit: typeof sim.releaseSpirit,
      haveResurrect: typeof sim.resurrectAtSpiritHealer,
      pos: [Math.round(p.pos.x), Math.round(p.pos.z)],
    };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.disconnect();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
