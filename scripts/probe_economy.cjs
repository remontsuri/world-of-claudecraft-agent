// throwaway probe: what the live client exposes for economy (recipes/stations/vendor/inv)
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
      try { out.recipeListLen = (sim.recipeList || []).length; } catch (_) { out.recipeListErr = 'no recipeList'; }
      try { out.stations = (sim.stationPlacements || []).slice(0, 4).map(s => ({ id: s.id || s.stationType, t: s.stationType || s.type, x: s.pos ? s.pos.x : s.x, z: s.pos ? s.pos.z : s.z })); } catch (e) { out.stationsErr = e.message; }
      try { out.invSample = (sim.player.inventory || []).slice(0, 6).map(i => ({ n: i.name || (i.def && i.def.name), q: i.quality, id: i.itemId || (i.def && i.def.id), cnt: i.count })); } catch (e) { out.invErr = e.message; }
      try {
        let v = null;
        for (const e of sim.entities.values()) { if (e.vendor || e.vendorItems || e.isVendor) { v = e; break; } }
        out.vendorFound = !!v;
        out.vendorItems = v && v.vendorItems ? (Array.isArray(v.vendorItems) ? v.vendorItems.slice(0, 4).map(x => x.id || x.itemId || String(x).slice(0, 24)) : Object.keys(v.vendorItems).slice(0, 4)) : null;
      } catch (e) { out.vErr = e.message; }
      // knownRecipes: try meta via resolve-like paths
      try {
        const cands = ['primary', 'playerMeta', 'meta'];
        for (const k of cands) { if (sim[k] && sim[k].meta && sim[k].meta.knownRecipes) out.knownVia = k; }
        // direct: some builds expose sim.meta
        if (sim.meta && sim.meta.knownRecipes) out.knownVia = 'sim.meta';
      } catch (e) { /* ignore */ }
      return out;
    });
    console.log(JSON.stringify(d, null, 1));
    break;
  }
  await b.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
