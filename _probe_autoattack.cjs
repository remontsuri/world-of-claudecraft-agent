const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const out = await page.evaluate(() => {
    const g=window.__game, sim=g.sim, p=sim.player;
    let best=null,bd=Infinity;
    for(const e of sim.entities.values()){if(e.kind!=='mob'||e.dead||(e.hp??0)<=0)continue;const dx=e.pos.x-p.pos.x,dz=e.pos.z-p.pos.z,d=Math.hypot(dx,dz);if(d<=45&&d<bd){bd=d;best=e;}}
    if(!best) return {error:'no mob'};
    const before = { auto_attack: p.auto_attack, inCombat: p.inCombat };
    // method 1: no arg
    try { sim.targetEntity(best.id); } catch(_){}
    try { sim.startAutoAttack(); } catch(e){ return {err1:e.message}; }
    const after_noarg = { auto_attack: p.auto_attack };
    // method 2: with p.id
    try { sim.startAutoAttack(p.id); } catch(e){ return {err2:e.message}; }
    const after_witharg = { auto_attack: p.auto_attack };
    // also test online.setMoveInput
    let moveOk=false;
    try { g.online.setMoveInput({forward:1}); moveOk=true; } catch(e){ moveOk='ERR:'+e.message; }
    return { before, after_noarg, after_witharg, moveOk, player_id: p.id };
  });
  console.log(JSON.stringify(out, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
