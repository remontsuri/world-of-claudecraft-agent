// throwaway probe 3: find the real bag container (bags.ts is 20K lines — check its API)
const { connect } = require('puppeteer-core');
(async () => {
  const b = await connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await b.pages();
  for (const p of pages) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (!u.includes('worldofclaudecraft')) continue;
    const d = await p.evaluate(() => {
      const sim = window.__game.sim;
      const out = {};
      out.simInvKeys = sim.inventory ? Object.keys(sim.inventory).slice(0, 8) : null;
      try { out.simInvProto = sim.inventory && sim.inventory.constructor && sim.inventory.constructor.name; } catch (_) {}
      // bags API?
      out.hasBags = typeof sim.bags;
      if (sim.bags) { out.bagsKeys = Object.keys(sim.bags).slice(0, 8); }
      // listItems / getBag?
      out.invMethods = sim.inventory ? Object.getOwnPropertyNames(Object.getPrototypeOf(sim.inventory)).slice(0, 15) : null;
      return out;
    });
    console.log(JSON.stringify(d, null, 1));
    break;
  }
  await b.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
