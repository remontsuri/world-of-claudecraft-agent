const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const g=window.__game, sim=g.sim;
    const out={};
    const p=sim.player; const pp=p.pos||{};
    let best=null,bd=1e9;
    if(sim.entities&&sim.entities.forEach){ sim.entities.forEach(e=>{
      if(e.kind==='npc'&&Array.isArray(e.questIds)&&e.questIds.length){
        const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9;
        if(d<bd){bd=d;best=e;}
      }}); }
    out.giver={name:best.name,dist:Math.round(bd),id:best.id};
    // inspect giver entity for interaction-related fields
    out.giverKeys = Object.keys(best).filter(k=>/interact|range|quest|dialog|radius|use/i.test(k));
    out.giverSample = { interactRange:best.interactRange, questIds:best.questIds };
    // Is there a server 'cmd' we can inspect?
    out.cmdType = typeof sim.cmd;
    // Try to find how the client opens quest dialog: search the whole window for a function that calls acceptQuest
    out.acceptQuestCaller = (sim.acceptQuest.toString().match(/this\.cmd\(\{[^}]*\}\)/)||[null])[0];
    // player move methods
    out.playerMoveMethods = Object.getOwnPropertyNames(Object.getPrototypeOf(p)||{}).filter(k=>/move|warp|teleport|setPos/i.test(k));
    // try global helpers for teleport
    out.globalTeleport = typeof window.teleport;
    out.globalWarp = typeof window.warp;
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
