const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // Replicate EXACT bridge case 0
  const before = await page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    let best=null,bd=Infinity;
    for(const e of sim.entities.values()){if(e.kind!=='mob'||e.dead||(e.hp??0)<=0)continue;const dx=e.pos.x-p.pos.x,dz=e.pos.z-p.pos.z,d=Math.hypot(dx,dz);if(d<=45&&d<bd){bd=d;best=e;}}
    if(!best) return {err:'no mob'};
    try { sim.targetEntity(best.id); } catch(e){ return {err:'target:'+e.message}; }
    try { if(typeof sim.setTarget==='function') sim.setTarget(best.id); } catch(_){}
    try { sim.startAutoAttack(); } catch(e){ return {err:'aa:'+e.message}; }
    try { if(typeof sim.castAbilityOn==='function') sim.castAbilityOn(best.id, 0); } catch(e){ return {err:'cast:'+e.message}; }
    return { id: best.id, hp: best.hp, auto_attack: p.auto_attack, targetId: p.targetId };
  });
  console.log('CASE0 applied:', JSON.stringify(before));
  await new Promise(r=>setTimeout(r,4000));
  const after = await page.evaluate((id) => {
    const sim = window.__game.sim; const e = sim.entities.get(id);
    return { hp: e?e.hp:'gone', dead: e?!e.dead:true };
  }, before.id||0);
  console.log('after 4s:', JSON.stringify(after), '| dmg', (before.hp!==undefined&&after.hp!=='gone')?(before.hp-after.hp):'n/a');
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
