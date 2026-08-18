const pptr=require('puppeteer-core');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  // ensure game loaded
  const ok=await page.evaluate(()=>!!(window.__game&&window.__game.sim)).catch(()=>false);
  if(!ok){ console.log('NO GAME'); await b.disconnect(); return; }
  const r=await page.evaluate(()=>{
    const g=window.__game, sim=g.sim;
    const p=sim.player, pp=p.pos||{};
    let best=null,bd=1e9;
    sim.entities.forEach(e=>{ if(e.kind==='npc'&&Array.isArray(e.questIds)&&e.questIds.length){ const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9; if(d<bd){bd=d;best=e;} } });
    return {giver:best.name,dist:Math.round(bd),questIds:best.questIds,id:best.id,before:Object.keys(sim.questLog||{}),selField: best.questIds.map((q,i)=>i+':'+q)};
  });
  console.log('BEFORE', JSON.stringify(r));
  // approach until <=3
  for(let i=0;i<40 && r.dist>3;i++){
    await page.evaluate((id)=>{ const g=window.__game,sim=g.sim; sim.targetEntity(id); sim.interact(); }, r.id);
    await sleep(300);
    const d=await page.evaluate((id)=>{ const sim=window.__game.sim; const p=sim.player,pp=p.pos||{}; const e=sim.entities.get(id); const ep=e?e.pos||{}:{}; return (pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):999; }, r.id);
    r.dist=Math.round(d);
  }
  console.log('AFTER APPROACH dist=',r.dist);
  // now try: interact then accept each quest by index
  for(let s=0;s<r.questIds.length;s++){
    const res=await page.evaluate((qid,s)=>{
      const sim=window.__game.sim;
      sim.interact();
      try{ sim.acceptQuest(qid,s); }catch(e){ return 'acceptErr:'+e.message; }
      return 'ok';
    }, r.questIds[s], s);
    await sleep(400);
    const log=await page.evaluate(()=>Object.keys(window.__game.sim.questLog||{}));
    console.log(`quest[${s}]=${r.questIds[s]} -> ${res} | logNow=${JSON.stringify(log)}`);
    if(log.length>0) break;
  }
  const finalLog=await page.evaluate(()=>Object.keys(window.__game.sim.questLog||{}));
  console.log('FINAL LOG', JSON.stringify(finalLog));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
