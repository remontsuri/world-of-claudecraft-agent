// throwaway probe 5: full inventory + knownRecipes + vendor stock + recipe reagents match
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
      // full inventory with names
      out.inv = [];
      (sim.inventory || []).forEach((slot, i) => {
        if (slot) out.inv.push({ i, id: slot.itemId || slot.def?.id, name: slot.name, q: slot.quality ?? (slot.def?.quality), cnt: slot.count || 1 });
      });
      // quality lives on def?
      if (out.inv.length) { out.qProbe = JSON.stringify(Object.keys(out.inv[0])) ; }
      // find player meta for knownRecipes: try g.online, g.world, sim['meta']
      const tries = {};
      try { tries.onlineKnown = !!(g.online && g.online.knownRecipes); } catch (_) {}
      try { tries.worldMeta = !!(g.world && g.world.meta && g.world.meta.knownRecipes); } catch (_) {}
      // scan g keys
      out.gKeys = Object.keys(g).slice(0, 25);
      out.tries = tries;
      // vendor stock: check a real merchant (Deeprock had empty array; look for 'merchant'/'trader')
      const vendors = [];
      for (const e of sim.entities.values()) {
        if (e.vendor || e.isVendor || e.vendorItems) vendors.push({ n: e.name, vi: Array.isArray(e.vendorItems) ? e.vendorItems.length : typeof e.vendorItems, v: !!e.vendor });
      }
      out.vendors = vendors.slice(0, 6);
      return out;
    });
    console.log(JSON.stringify(d, null, 1));
    break;
  }
  await b.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
