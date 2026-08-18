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
    return best ? { id: best.id, name: best.name, hp: best.hp } : null;
  });
  const before = await pick();
  if (!before) { console.log('NO MOB'); await browser.disconnect(); return; }
  console.log('BEFORE:', JSON.stringify(before));
  // try several attack paths
  const r1 = await page.evaluate((id) => {
    const g = window.__game, sim = g.sim, p = sim.player;
    let log = [];
    try { sim.targetEntity(id); } catch(e){ log.push('targetEntity:'+e.message); }
    log.push('target_after_targetEntity=' + (p.target ? p.target.id : null));
    try { sim.startAutoAttack(); } catch(e){ log.push('startAA:'+e.message); }
    log.push('target_after_startAA=' + (p.target ? p.target.id : null));
    log.push('inCombat=' + !!p.inCombat);
    try { if (typeof sim.setTarget === 'function') { sim.setTarget(id); log.push('setTarget ok'); } } catch(e){ log.push('setTarget:'+e.message); }
    log.push('target_after_setTarget=' + (p.target ? p.target.id : null));
    return log;
  }, before.id);
  console.log('ATTEMPT1:', JSON.stringify(r1));
  for (let i = 0; i < 4; i++) {
    await new Promise(r => setTimeout(r, 1000));
    const cur = await page.evaluate((id) => {
      const e = window.__game.sim.entities.get(id);
      const p = window.__game.sim.player;
      return { hp: e ? e.hp : 'gone', dead: e ? !!e.dead : true, target: p.target ? p.target.id : null, inCombat: !!p.inCombat };
    }, before.id);
    console.log(`t+${i+1}s:`, JSON.stringify(cur));
  }
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
