const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes('worldofclaudecraft.com')) || pages[0];
  const s = await page.evaluate(() => {
    const g = window.__game; const sim = g.sim; const p = sim.player;
    return {
      hp: p.hp, maxHp: p.maxHp, hpPct: (p.hp/Math.max(1,p.maxHp))*100,
      dead: p.dead, inCombat: p.inCombat, pos: {x:p.pos.x, z:p.pos.z}, facing: p.facing,
      level: p.level,
      entityCount: sim.entities.size,
      vendorInEntities: [...sim.entities.values()].filter(e=>e.kind==='npc').map(e=>({name:e.name,dist:Math.hypot(e.pos.x-p.pos.x,e.pos.z-p.pos.z)})),
      releaseSpirit: typeof sim.releaseSpirit, resurrectAtSpiritHealer: typeof sim.resurrectAtSpiritHealer,
    };
  });
  console.log(JSON.stringify(s, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR', e.message); process.exit(1);});
