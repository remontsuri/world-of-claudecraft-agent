const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim, p=sim.player, pp=p.pos||{};
    let nh=1e9; sim.entities.forEach(e=>{ if(e.kind==='mob'&&!e.dead&&(e.hp??0)>0&&e.hostile){ const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9; if(d<nh)nh=d; } });
    let giver=null,gd=1e9; sim.entities.forEach(e=>{ if(e.kind==='npc'&&Array.isArray(e.questIds)&&e.questIds.length){ const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9; if(d<gd){gd=d;giver=e;} } });
    return {activeQuests:Object.keys(sim.questLog||{}), nearestHostile:Math.round(nh), giverDist:Math.round(gd), giverName:giver?giver.name:null, questDialogOpen: window.__game.hud?.questDialogOpen};
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
