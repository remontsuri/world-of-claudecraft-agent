const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim, g=window.__game;
    const out={};
    const p=sim.player; const pp=p.pos||{};
    let best=null,bd=1e9;
    if(sim.entities&&sim.entities.forEach){ sim.entities.forEach(e=>{
      if(e.kind==='npc'&&Array.isArray(e.questIds)&&e.questIds.length){
        const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9;
        if(d<bd){bd=d;best=e;}
      }}); }
    out.giver={name:best.name,dist:Math.round(bd),questIds:best.questIds,id:best.id};
    // teleport-like? check for a 'warp' or 'moveTo' on player
    out.playerMoveKeys = Object.getOwnPropertyNames(Object.getPrototypeOf(p)||{}).filter(k=>/move|warp|teleport|set/i.test(k));
    // try simulating exact UI: target + interact on the NPC via controller
    try{ sim.targetEntity(best.id); }catch(e){ out.tErr=e.message; }
    // call controller talk/interact if exists
    out.ctrlKeys = g.controller ? Object.getOwnPropertyNames(Object.getPrototypeOf(g.controller)||{}).filter(k=>/interact|talk|quest|accept|click|use/i.test(k)) : 'no ctrl';
    // check g.dialog / g.openDialog
    out.hasDialog = typeof g.dialog;
    out.hasOpenDialog = typeof g.openDialog;
    out.hasTalk = typeof g.talk;
    // inspect pendingQuestCommands after a target
    out.pendingBefore = [...(sim.pendingQuestCommands?.keys?.()||[])];
    try{ sim.interact(); }catch(e){ out.iErr=e.message; }
    return out;
  });
  await new Promise(r=>setTimeout(r,500));
  const r2=await page.evaluate(()=>{
    const sim=window.__game.sim;
    return { pendingAfter:[...(sim.pendingQuestCommands?.keys?.()||[])], log:Object.keys(sim.questLog||{}), questGiverDialogOpen: typeof sim.questGiverOpen };
  });
  console.log(JSON.stringify({...r,...r2},null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
