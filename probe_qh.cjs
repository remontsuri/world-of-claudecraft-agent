const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim, p=sim.player, pp=p.pos||{};
    let mobs=0, hostileNear=0, nearestMob=1e9;
    sim.entities.forEach(e=>{
      if(e.kind==='mob' && !e.dead && (e.hp??0)>0){
        mobs++;
        const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9;
        if(e.hostile && d<nearestMob) nearestMob=d;
        if(d<=60) hostileNear++;
      }
    });
    // givers
    let giver=null,gd=1e9;
    sim.entities.forEach(e=>{ if(e.kind==='npc'&&Array.isArray(e.questIds)&&e.questIds.length){ const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9; if(d<gd){gd=d;giver=e;} } });
    return {mobsTotal:mobs, hostileWithin60:hostileNear, nearestMobDist:Math.round(nearestMob), giverDist:Math.round(gd), giverName:giver?giver.name:null, activeQuests:Object.keys(sim.questLog||{}).length};
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
