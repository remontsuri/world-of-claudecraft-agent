const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim;
    const out={};
    const p=sim.player; const pp=p.pos||{};
    // find nearest giver
    let best=null,bd=1e9;
    if(sim.entities&&sim.entities.forEach){ sim.entities.forEach(e=>{
      if(e.kind==='npc'&&Array.isArray(e.questIds)&&e.questIds.length){
        const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9;
        if(d<bd){bd=d;best={id:e.id,name:e.name,questIds:e.questIds,dist:d};}
      }}); }
    out.nearestGiver=best;
    out.beforeLog=Object.keys(sim.questLog||{});
    out.beforeDone=Object.keys(sim.questsDone||{});
    // pick a non-prof quest
    const qid = best ? best.questIds.find(q=>!/^q_prof/.test(q)) : null;
    out.tryQid=qid;
    if(qid){
      try{ sim.acceptQuest(qid,0); out.acceptErr=null; }catch(e){ out.acceptErr=e.message; }
      // wait a tick for command to process
    }
    return out;
  });
  // give it a moment, then re-read
  await new Promise(r=>setTimeout(r,800));
  const r2=await page.evaluate(()=>{
    const sim=window.__game.sim;
    return { afterLog:Object.keys(sim.questLog||{}), afterDone:Object.keys(sim.questsDone||{}) };
  });
  console.log(JSON.stringify({...r,...r2},null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
