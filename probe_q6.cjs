const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim;
    const out={kinds:{}};
    const givers=[];
    const p=sim.player;
    const pp=p.pos||{};
    if(sim.entities && sim.entities.forEach){
      sim.entities.forEach(e=>{
        const k=e.kind||'?';
        out.kinds[k]=(out.kinds[k]||0)+1;
        const qids=(Array.isArray(e.questIds)?e.questIds:(e.questIds?Object.keys(e.questIds):[]));
        if(qids.length>0){
          const ep=e.pos||{};
          givers.push({id:e.id,name:e.name,kind:k,questIds:qids,
            dist:(pp.x!==undefined&&ep.x!==undefined)?Math.round(Math.hypot(ep.x-pp.x,ep.z-pp.z)):-1});
        }
      });
    }
    out.giversWithQuests = givers.slice(0,20);
    // also: any 'interact' method on sim
    out.simInteract = typeof sim.interact;
    out.simTalk = typeof sim.talk;
    out.simRequestQuests = typeof sim.requestQuests;
    // how does UI open quest dialog? look for 'openQuest' or 'questGiver'
    out.simKeys = Object.keys(sim).filter(k=>/interact|talk|dialog|giver|offer|request/i.test(k));
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
