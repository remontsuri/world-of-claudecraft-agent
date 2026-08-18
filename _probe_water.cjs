// _probe_water.cjs — inspect live player object for water/zone flags + find giver
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
    // dump player keys that hint at water/zone
    const keys = Object.keys(p).filter(k => /water|zone|swim|sea|ground|moving|submerged|env/i.test(k));
    const flag = {};
    for (const k of keys) flag[k] = p[k];
    // also check sim-level helpers
    const simFlags = {};
    for (const k of ['isInWater','inWater','getZone','zoneAt']) {
      try { simFlags[k] = typeof sim[k]; } catch(e) {}
    }
    // find giver/NPC with quest
    let giver = null;
    for (const e of sim.entities.values()) {
      if ((e.questIds && e.questIds.length) || (e.questId)) {
        giver = { kind: e.kind, name: e.name, x: e.pos ? Math.round(e.pos.x):null, z: e.pos?Math.round(e.pos.z):null };
        break;
      }
    }
    return {
      pos: [Math.round(p.pos.x), Math.round(p.pos.z)],
      playerWaterKeys: keys,
      playerWaterFlags: flag,
      simHelpers: simFlags,
      giver,
      entityKinds: [...new Set([...sim.entities.values()].map(e=>e.kind))],
    };
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.disconnect();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
