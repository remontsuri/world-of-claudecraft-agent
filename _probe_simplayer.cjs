const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // EXACT replica of bridge snapshot() — what does it see?
  const out = await page.evaluate(() => {
    try {
      const g = window.__game, sim = g.sim, p = sim.player;
      if (!p) return { ERROR: 'sim.player is undefined', sim_player_keys: sim.player? 'has': 'undefined', online_playerId: g.online?.playerId };
      if (!p.pos) return { ERROR: 'sim.player.pos undefined', player_keys: Object.keys(p).slice(0,20) };
      const nearby=[];
      for (const e of sim.entities.values()) {
        if (!e.pos) continue;
        const dx=e.pos.x-p.pos.x, dz=e.pos.z-p.pos.z, d=Math.hypot(dx,dz);
        if (d>70) continue;
        nearby.push({kind:e.kind,name:e.name,questIds:e.questIds||null});
      }
      return { OK: true, player_id: p.id, player_pos:[p.pos.x,p.pos.z], nearby: nearby.length, npcs: nearby.filter(x=>x.kind==='npc').length, withQ: nearby.filter(x=>x.questIds&&x.questIds.length).length };
    } catch(e) { return { THREW: e.message }; }
  });
  console.log(JSON.stringify(out, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
