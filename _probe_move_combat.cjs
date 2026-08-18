const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const before = await page.evaluate(() => {
    const p = window.__game.sim.player;
    return { x: p.pos.x, z: p.pos.z, hasOnline: !!window.__game.online, hasSetMove: !!(window.__game.online && window.__game.online.setMoveInput) };
  });
  // correct movement per skill: online.setMoveInput
  await page.evaluate(() => { try { window.__game.online.setMoveInput({ forward: 1 }); } catch(e){ return 'moveErr:'+e.message; } });
  await new Promise(r => setTimeout(r, 2000));
  await page.evaluate(() => { try { window.__game.online.setMoveInput({ forward: 0 }); } catch(_){} });
  const after = await page.evaluate(() => { const p = window.__game.sim.player; return { x: p.pos.x, z: p.pos.z }; });
  const moved = Math.hypot(after.x-before.x, after.z-before.z);
  // combat via startAutoAttack(p.id)
  const c = await page.evaluate(() => {
    const sim = window.__game.sim, p = sim.player;
    let best=null,bd=Infinity;
    for(const e of sim.entities.values()){if(e.kind!=='mob'||e.dead||(e.hp??0)<=0)continue;const dx=e.pos.x-p.pos.x,dz=e.pos.z-p.pos.z,d=Math.hypot(dx,dz);if(d<=45&&d<bd){bd=d;best=e;}}
    if(!best) return {err:'no mob'};
    const k0 = (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || p.kills || 0;
    try { sim.targetEntity(best.id); } catch(_){}
    try { sim.startAutoAttack(p.id); } catch(e){ return {err:e.message}; }
    return { id: best.id, hp0: best.hp, k0 };
  });
  await new Promise(r => setTimeout(r, 4000));
  const c2 = await page.evaluate((id) => {
    const sim = window.__game.sim; const e = sim.entities.get(id);
    const k1 = (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || sim.player.kills || 0;
    return { hp: e ? e.hp : 'gone', k1 };
  }, c.id || 0);
  console.log('MOVE: before', before.x.toFixed(1), before.z.toFixed(1), '-> after', after.x.toFixed(1), after.z.toFixed(1), '| moved', moved.toFixed(1));
  console.log('COMBAT:', JSON.stringify(c), '->', JSON.stringify(c2), '| dmg', c.hp0!==undefined && c2.hp!=='gone' ? (c.hp0 - c2.hp) : 'n/a');
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
