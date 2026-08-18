const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim;
    const out={};
    const p=sim.player;
    out.playerKeys = Object.keys(p).filter(k=>/pos|loc|x|z|coord/i.test(k)).slice(0,10);
    out.playerPosCandidates = {};
    for(const k of ['position','pos','loc','location','coord','x']){ if(p[k]!==undefined) out.playerPosCandidates[k]= (typeof p[k]==='object')?Object.keys(p[k]):p[k]; }
    // entity sample: enumerate types
    const types={};
    if(sim.entities && sim.entities.forEach){
      sim.entities.forEach(e=>{ const t=e.type||'?'; types[t]=(types[t]||0)+1; });
    }
    out.entityTypes = types;
    // full field scan of an NPC-like entity (interactable)
    let npc=null;
    if(sim.entities && sim.entities.forEach){
      sim.entities.forEach(e=>{ if(!npc && (/human|npc|merchant|vendor|quest|giver|citizen/i.test(e.type||''))) npc=e; });
    }
    if(!npc && sim.entities && sim.entities.forEach){
      // fallback: any entity with 'name' and not mob
      sim.entities.forEach(e=>{ if(!npc && e.name && !/bandit|wolf|rat|skeleton|spider|boar|slime/i.test(e.name)) npc=e; });
    }
    if(npc){
      out.npcType = npc.type;
      out.npcName = npc.name;
      out.npcKeys = Object.keys(npc).slice(0,40);
      out.npcQuestFields = Object.keys(npc).filter(k=>/quest/i.test(k)).reduce((a,k)=>{a[k]=npc[k];return a;},{});
    }
    // acceptQuest source
    try{ out.acceptQuestSrc = sim.acceptQuest.toString().slice(0,300); }catch(e){}
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
