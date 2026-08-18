const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.log('NO_GAME_TAB'); await browser.disconnect(); return; }
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', { timeout: 15000 });
  // Try the exact sequence the bridge case 0 uses, but ALSO add setTarget + castAbilityOn
  const before = await page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    let best = null, bd = Infinity;
    for (const e of sim.entities.values()) {
      if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0) continue;
      const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
      if (d <= 45 && d < bd) { bd = d; best = e; }
    }
    if (!best) return null;
    try { sim.targetEntity(best.id); } catch(_) {}
    try { sim.setTarget && sim.setTarget(best.id); } catch(_) {}
    try { sim.startAutoAttack(); } catch(_) {}
    try { sim.castAbilityOn && sim.castAbilityOn(best.id, 0); } catch(_) {}
    return { id: best.id, hp: best.hp };
  });
  if (!before) { console.log('NO MOB'); await browser.disconnect(); return; }
  console.log('BEFORE:', JSON.stringify(before));
  for (let i = 0; i < 5; i++) {
    await new Promise(r => setTimeout(r, 1000));
    const cur = await page.evaluate((id) => {
      const e = window.__game.sim.entities.get(id);
      return { hp: e ? e.hp : 'gone', dead: e ? !!e.dead : true };
    }, before.id);
    console.log(`t+${i+1}s:`, JSON.stringify(cur));
  }
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
