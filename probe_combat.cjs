const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes('worldofclaudecraft')) || pages[0];
  const info = await page.evaluate(() => {
    const g = window.__game; const sim = g.sim; const p = sim.player;
    let liveMobs = 0, near = 0;
    for (const e of sim.entities.values()) {
      if (e.kind === 'mob' && !e.dead && (e.hp ?? 0) > 0) {
        liveMobs++;
        const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z;
        if (Math.hypot(dx, dz) <= 8) near++;
      }
    }
    return {
      hp: Math.round(p.hp), maxHp: Math.round(p.maxHp),
      dead: p.dead, inCombat: p.inCombat, autoAttack: p.autoAttack,
      targetId: p.targetId,
      hasTarget: p.targetId != null && sim.entities.get(p.targetId) != null,
      targetDead: p.targetId != null ? (sim.entities.get(p.targetId)?.dead ?? 'no-entity') : 'none',
      level: p.level,
      pos: { x: Math.round(p.pos.x), z: Math.round(p.pos.z) },
      liveMobs, nearMobs: near,
      counters: { kills: sim.deedStats?.counters?.kills, damage: sim.deedStats?.counters?.damage, deaths: sim.deedStats?.counters?.deaths },
    };
  });
  console.log(JSON.stringify(info, null, 2));
  await browser.disconnect();
})().catch(e => { console.error(e); process.exit(1); });
