const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // Replicate EXACTLY what the bridge snapshot() does, but log intermediate state
  const diag = await page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    const out = { player_exists: !!p, player_pos: p ? [p.pos?.x, p.pos?.z] : null,
      entities_size: sim.entities ? sim.entities.size : 'no entities',
      sample_entity: null };
    let first = null;
    for (const e of sim.entities.values()) { first = e; break; }
    if (first) out.sample_entity = { kind: first.kind, has_pos: !!first.pos, pos: first.pos?[first.pos.x,first.pos.z]:null };
    // now replicate the nearby loop exactly
    const nearby=[]; let skipped_dist=0, skipped_nopos=0;
    for (const e of sim.entities.values()) {
      if (!e.pos) { skipped_nopos++; continue; }
      const dx=e.pos.x-p.pos.x, dz=e.pos.z-p.pos.z, d=Math.hypot(dx,dz);
      if (d>70){skipped_dist++;continue;}
      nearby.push({kind:e.kind,name:e.name,dist:Math.round(d)});
    }
    out.nearby_count = nearby.length;
    out.skipped_dist = skipped_dist; out.skipped_nopos = skipped_nopos;
    out.nearby_sample = nearby.slice(0,5);
    return out;
  });
  console.log(JSON.stringify(diag, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
