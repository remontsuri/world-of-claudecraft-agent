const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim;
    const out={};
    // 1) sim methods containing 'quest'
    out.simQuestMethods = Object.keys(sim).filter(k=>/quest/i.test(k));
    // 2) entity types near player
    const ppos = sim.player.position;
    out.playerPos = ppos ? {x:Math.round(ppos.x),z:Math.round(ppos.z)} : null;
    const givers=[];
    if(sim.entities && sim.entities.forEach){
      sim.entities.forEach(e=>{
        const t=(e.type||'').toLowerCase();
        const name=e.name||e.id||'?';
        const isGiver = /quest/i.test(t) || e.questGiver===true || (e.offersQuests&&e.offersQuests.length) || (e.quests&&e.quests.length);
        if(isGiver){
          const ep=e.position||{};
          givers.push({id:e.id,name,type:e.type,questGiver:e.questGiver,offers:e.offersQuests,quests:e.quests,
            dist: ppos&&ep?Math.round(Math.hypot(ep.x-ppos.x,ep.z-ppos.z)):-1});
        }
      });
    }
    out.questGivers = givers.slice(0,15);
    // 3) npc methods for interaction
    if(sim.entities && sim.entities.forEach){
      let npcSample=null;
      sim.entities.forEach(e=>{ if(!npcSample && /npc/i.test(e.type||'')) npcSample=e; });
      if(npcSample){
        out.npcSampleKeys = Object.keys(npcSample).filter(k=>/quest|interact|talk|offer|accept/i.test(k));
        out.npcSampleType = npcSample.type;
      }
    }
    // 4) try known accept patterns
    out.hasAcceptQuest = typeof sim.acceptQuest;
    out.hasStartQuest = typeof sim.startQuest;
    out.hasOfferQuest = typeof sim.offerQuest;
    out.hasCompleteQuest = typeof sim.completeQuest;
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
