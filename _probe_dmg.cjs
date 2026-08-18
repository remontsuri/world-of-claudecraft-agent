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
  const pick = () => page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    let best = null, bd = Infinity;
    for (const e of sim.entities.values()) {
      if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0) continue;
      const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
      if (d <= 45 && d < bd) { bd = d; best = e; }
    }
    if (!best) return null;
    return { id: best.id, name: best.name, hp: best.hp, maxHp: best.maxHp };
  });
  const before = await pick();
  if (!before) { console.log('NO MOB'); await browser.disconnect(); return; }
  console.log('BEFORE:', JSON.stringify(before));
  await page.evaluate((id) => {
    const g = window.__game, sim = g.sim;
    try { sim.targetEntity(id); } catch(_) {}
    try { sim.startAutoAttack(); } catch(_) {}
  }, before.id);
  // sample HP a few times over 4s
  for (let i = 0; i < 4; i++) {
    await new Promise(r => setTimeout(r, 1000));
    const cur = await page.evaluate((id) => {
      const e = window.__game.sim.entities.get(id);
      return e ? { hp: e.hp, dead: !!e.dead } : { gone: true };
    }, before.id);
    console.log(`t+${i+1}s:`, JSON.stringify(cur));
  }
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
