const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim, p=sim.player, pp=p.pos||{};
    let nearestHostile=1e9;
    sim.entities.forEach(e=>{ if(e.kind==='mob'&&!e.dead&&(e.hp??0)>0&&e.hostile){ const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9; if(d<nearestHostile)nearestHostile=d; } });
    return {inCombat:p.inCombat, nearestHostile:Math.round(nearestHostile), autoAttack:p.autoAttack};
  });
  console.log(JSON.stringify(r));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
