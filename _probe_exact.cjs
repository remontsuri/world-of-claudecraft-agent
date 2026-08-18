const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  // Do NOT bringToFront — replicate bridge exactly
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const out = await page.evaluate(() => {
    // EXACT replica of bridge snapshot() body
    const g = window.__game, sim = g.sim, p = sim.player;
    const debug = [];
    let aldric = null;
    for (const e of sim.entities.values()) {
      if (!e.pos) continue;
      const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
      if (d > 70) continue;
      if (e.kind === 'npc') {
        debug.push({ name: e.name, q: e.questIds || null });
        if (e.name === 'Brother Aldric') aldric = e.questIds || null;
      }
    }
    return { npc_debug: debug, aldric };
  });
  console.log(JSON.stringify(out, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
