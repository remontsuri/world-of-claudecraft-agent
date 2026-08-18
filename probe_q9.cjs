const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim;
    const out={};
    const p=sim.player; const pp=p.pos||{};
    let best=null,bd=1e9;
    if(sim.entities&&sim.entities.forEach){ sim.entities.forEach(e=>{
      if(e.kind==='npc'&&Array.isArray(e.questIds)&&e.questIds.length){
        const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9;
        if(d<bd){bd=d;best=e;}
      }}); }
    out.nearest={name:best.name,dist:Math.round(bd),questIds:best.questIds};
    out.before=Object.keys(sim.questLog||{});
    // target NPC
    try{ sim.targetEntity(best.id); out.targetErr=null; }catch(e){ out.targetErr=e.message; }
    try{ sim.interact(); out.interactErr=null; }catch(e){ out.interactErr=e.message; }
    return out;
  });
  await new Promise(r=>setTimeout(r,500));
  // try accept with selection 0..12
  const res=await page.evaluate(()=>{
    const sim=window.__game.sim;
    const log=Object.keys(sim.questLog||{});
    const tried=[];
    for(let s=0;s<12;s++){
      try{ sim.acceptQuest('q_boars',s); tried.push('q_boars@'+s+':ok'); }
      catch(e){ tried.push('q_boars@'+s+':ERR '+e.message.slice(0,30)); }
    }
    return {logAfterEach:Object.keys(sim.questLog||{}), tried};
  });
  await new Promise(r=>setTimeout(r,500));
  const r3=await page.evaluate(()=>{
    const sim=window.__game.sim;
    return { finalLog:Object.keys(sim.questLog||{}), done:Object.keys(sim.questsDone||{}) };
  });
  console.log(JSON.stringify({...r,...res,...r3},null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
