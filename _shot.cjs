// _shot.cjs — screenshot the live WoC game tab via CDP (same :9222 the bridge uses)
const { connect } = require('puppeteer-core');
const fs = require('fs');

const CDP = 'http://127.0.0.1:9222';
const OUT = process.argv[2] || 'D:/world-of-claudecraft/_shot.png';

(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.error('no game tab'); process.exit(2); }
  await page.bringToFront();
  await new Promise(r => setTimeout(r, 800));
  const buf = await page.screenshot({ type: 'png' });
  fs.writeFileSync(OUT, buf);
  console.log('saved', OUT, buf.length, 'bytes');
  // also dump a compact entity/player readout from the live sim
  try {
    const dbg = await page.evaluate(() => {
      const g = window.__game, sim = g.sim, p = sim.player;
      const near = [];
      for (const e of sim.entities.values()) {
        if (!e.pos) continue;
        const d = Math.hypot(e.pos.x - p.pos.x, e.pos.z - p.pos.z);
        if (d > 80) continue;
        near.push({ kind: e.kind, name: e.name, hp: e.hp, d: Math.round(d), x: Math.round(e.pos.x), z: Math.round(e.pos.z) });
      }
      return { pos: [Math.round(p.pos.x), Math.round(p.pos.z)], hp: p.hp, maxHp: p.maxHp, facing: Math.round(p.facing*100)/100, near };
    });
    console.log(JSON.stringify(dbg));
  } catch (e) { console.error('dbg err', e.message); }
  await browser.disconnect();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
