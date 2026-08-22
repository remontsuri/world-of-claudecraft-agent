// throwaway probe 4: bag slots content shape
const { connect } = require('puppeteer-core');
(async () => {
  const b = await connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await b.pages();
  for (const p of pages) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (!u.includes('worldofclaudecraft')) continue;
    const d = await p.evaluate(() => {
      const sim = window.__game.sim;
      const out = { bags: [], simInvNonEmpty: [] };
      // sim.inventory is an array of slots (8 keys)
      (sim.inventory || []).forEach((slot, i) => {
        if (slot) out.simInvNonEmpty.push({ i, name: slot.name, q: slot.quality, id: slot.itemId || slot.def?.id, cnt: slot.count });
      });
      // sim.bags: array of bags, each with slots?
      if (sim.bags && typeof sim.bags.forEach === 'function') {
        sim.bags.forEach((bag, bi) => {
          const entry = { bi, size: bag ? bag.size ?? bag.length : null };
          if (bag && typeof bag.forEach === 'function') {
            entry.slots = [];
            let n = 0;
            bag.forEach((s, si) => { if (s && n++ < 4) entry.slots.push({ si, name: s.name, q: s.quality }); });
          }
          out.bags.push(entry);
        });
      } else if (Array.isArray(sim.bags)) {
        sim.bags.forEach((bag, bi) => {
          const arr = bag && (bag.slots || bag);
          const list = Array.isArray(arr) ? arr : [];
          out.bags.push({ bi, len: list.length, sample: list.filter(Boolean).slice(0, 3).map(s => ({ name: s.name, q: s.quality })) });
        });
      }
      return out;
    });
    console.log(JSON.stringify(d, null, 1));
    break;
  }
  await b.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
