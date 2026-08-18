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
  try { await page.waitForFunction('!!window.__game && !!window.__game.sim', { timeout: 15000 }); }
  catch(e){ console.log('NO __game'); await browser.disconnect(); return; }
  const info = await page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    let mobs_near = 0, mobs_total = 0, nearest = null, nd = Infinity;
    for (const e of sim.entities.values()) {
      if (e.kind === 'mob') {
        mobs_total++;
        if (e.dead || (e.hp ?? 0) <= 0) continue;
        const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
        if (d <= 70) mobs_near++;
        if (d < nd) { nd = d; nearest = { name: e.name, d: Math.round(d), hp: e.hp }; }
      }
    }
    return {
      mobs_total, mobs_near, nearest,
      kills_before: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || p.kills || 0,
      player_pos: [Math.round(p.pos.x), Math.round(p.pos.z)],
      in_combat: !!p.inCombat,
    };
  });
  console.log('BEFORE:', JSON.stringify(info));
  // try to attack nearest mob directly
  const atk = await page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    let best = null, bd = Infinity;
    for (const e of sim.entities.values()) {
      if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0) continue;
      const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
      if (d <= 45 && d < bd) { bd = d; best = e; }
    }
    if (!best) return { ok: false, reason: 'no mob in 45yd' };
    try { sim.targetEntity(best.id); } catch (e) { return { ok: false, targetErr: e.message }; }
    try { sim.startAutoAttack(); } catch (e) { return { ok: false, atkErr: e.message }; }
    return { ok: true, target: best.name };
  });
  console.log('ATTACK:', JSON.stringify(atk));
  await new Promise(r => setTimeout(r, 2500));
  const after = await page.evaluate(() => {
    const g = window.__game, sim = g.sim;
    return { kills_after: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || sim.player.kills || 0 };
  });
  console.log('AFTER:', JSON.stringify(after));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
