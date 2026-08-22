// throwaway probe 2: inventory shape (bags.ts), vendor stock source
const { connect } = require('puppeteer-core');
(async () => {
  const b = await connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await b.pages();
  for (const p of pages) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (!u.includes('worldofclaudecraft')) continue;
    const d = await p.evaluate(() => {
      const g = window.__game, sim = g.sim;
      const out = {};
      // bags may live elsewhere: check player fields
      out.playerKeys = Object.keys(sim.player).filter(k => /bag|inv|item/i.test(k));
      // probe each candidate
      for (const k of out.playerKeys) {
        try {
          const v = sim.player[k];
          if (v && typeof v.size === 'number') out[k + '_size'] = v.size;
          else if (Array.isArray(v)) out[k + '_len'] = v.length;
        } catch (_) {}
      }
      // sim-level inventory?
      out.simInvType = typeof sim.inventory;
      // sample first non-empty bag container
      for (const k of out.playerKeys) {
        const v = sim.player[k];
        if (v && typeof v.forEach === 'function' && v.size > 0) {
          out.sampleFrom = k;
          let n = 0; out.items = [];
          v.forEach((val, key) => { if (n++ < 6) out.items.push({ key, name: val.name, q: val.quality, id: val.itemId || val.def?.id, cnt: val.count }); });
          break;
        }
        if (Array.isArray(v) && v.length > 0) {
          out.sampleFrom = k; out.items = v.slice(0, 6).map(x => ({ name: x.name, q: x.quality, id: x.itemId || x.def?.id, cnt: x.count }));
          break;
        }
      }
      return out;
    });
    console.log(JSON.stringify(d, null, 1));
    break;
  }
  await b.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
