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
    // try interact() then accept the first non-prof quest
    const qid = best.questIds.find(q=>!/^q_prof/.test(q));
    out.qid=qid;
    try{ sim.interact(); out.interactErr=null; }catch(e){ out.interactErr=e.message; }
    return out;
  });
  await new Promise(r=>setTimeout(r,600));
  const r2=await page.evaluate((qid)=>{
    const sim=window.__game.sim;
    const out={ afterInteractLog:Object.keys(sim.questLog||{}) };
    // now try accept
    try{ sim.acceptQuest(qid,0); out.acceptErr=null; }catch(e){ out.acceptErr=e.message; }
    return out;
  }, r.qid);
  await new Promise(r=>setTimeout(r,600));
  const r3=await page.evaluate(()=>{
    const sim=window.__game.sim;
    return { afterAcceptLog:Object.keys(sim.questLog||{}), done:Object.keys(sim.questsDone||{}) };
  });
  console.log(JSON.stringify({...r,...r2,...r3},null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
