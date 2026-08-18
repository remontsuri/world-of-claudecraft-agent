const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // EXACT replica of bridge snapshot() body, but for a specific NPC
  const out = await page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    const result = { player_id: p?.id, entities: sim.entities.size, npcs_found: 0, aldric: null };
    for (const e of sim.entities.values()) {
      if (e.kind === 'npc') {
        result.npcs_found++;
        if (e.name === 'Brother Aldric') {
          result.aldric = { questIds: e.questIds || null, kind: e.kind, has_pos: !!e.pos };
        }
      }
    }
    return result;
  });
  console.log(JSON.stringify(out, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
