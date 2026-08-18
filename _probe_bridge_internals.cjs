const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // Replicate EXACTLY what the bridge snapshot() does, INCLUDING the reconnect() check
  const out = await page.evaluate(() => {
    const g = window.__game, sim = g.sim;
    const player = sim.player;
    const ents = sim.entities ? sim.entities.size : 'no entities';
    // now replicate the nearby loop
    let nearby=0;
    if (player && player.pos) {
      for (const e of sim.entities.values()) {
        if (!e.pos) continue;
        const dx=e.pos.x-player.pos.x, dz=e.pos.z-player.pos.z, d=Math.hypot(dx,dz);
        if (d>70) continue;
        nearby++;
      }
    }
    return { has_game: !!g, has_sim: !!sim, player_exists: !!player, player_pos: player&&player.pos?[player.pos.x,player.pos.z]:null, entities: ents, nearby_count: nearby };
  });
  console.log('BRIDGE-EQUIVALENT EVAL:', JSON.stringify(out));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
