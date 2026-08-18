const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const g=window.__game, sim=g.sim;
    const out={};
    // controller API
    out.ctrlAll = g.controller ? Object.getOwnPropertyNames(Object.getPrototypeOf(g.controller)) : 'no ctrl';
    // how does UI open quest dialog? look at sim methods around 'questGiver'/'dialog'
    out.simQuestMethods = Object.keys(sim).filter(k=>/quest|dialog|giver|interact|talk|accept|open/i.test(k));
    // pendingQuestCommands type
    out.pqcType = sim.pendingQuestCommands ? (sim.pendingQuestCommands.constructor.name) : 'none';
    // is there a method that returns available quests for an entity?
    out.hasGetQuests = typeof sim.getAvailableQuests;
    out.hasQuestDialog = typeof sim.questGiverQuests;
    out.hasOpenQuest = typeof sim.openQuestGiver;
    // look at interact source
    try{ out.interactSrc = sim.interact.toString().slice(0,400); }catch(e){ out.interactSrc='ERR'; }
    // look at targetEntity source
    try{ out.targetSrc = sim.targetEntity.toString().slice(0,300); }catch(e){}
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
