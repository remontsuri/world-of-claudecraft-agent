const pptr=require('puppeteer-core');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const ok=await page.evaluate(()=>!!(window.__game&&window.__game.sim&&window.__game.hud)).catch(()=>false);
  if(!ok){ console.log('NO GAME/HUD'); await b.disconnect(); return; }
  const r=await page.evaluate(()=>{
    const g=window.__game, sim=g.sim, hud=g.hud;
    const p=sim.player, pp=p.pos||{};
    let best=null,bd=1e9;
    sim.entities.forEach(e=>{ if(e.kind==='npc'&&Array.isArray(e.questIds)&&e.questIds.length){ const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9; if(d<bd){bd=d;best=e;} } });
    return {hasHud:!!hud, hasOpen:typeof hud.openQuestDialog, giver:best.name, id:best.id, dist:Math.round(bd), before:Object.keys(sim.questLog||{})};
  });
  console.log('BEFORE', JSON.stringify(r));
  if(!r.hasHud||r.dist>3){ console.log('need to be <=3yd and have hud; dist=',r.dist); await b.disconnect(); return; }
  // open dialog
  await page.evaluate((id)=>{ window.__game.hud.openQuestDialog(id); }, r.id);
  await sleep(500);
  const afterOpen=await page.evaluate(()=>({open:window.__game.hud.questDialogOpen, log:Object.keys(window.__game.sim.questLog||{})}));
  console.log('AFTER OPEN', JSON.stringify(afterOpen));
  // accept first non-prof quest
  const qid=r.questIds? r.questIds.find(q=>!/^q_prof/.test(q)):null;
  if(!qid){ console.log('no plain quest'); await b.disconnect(); return; }
  await page.evaluate((qid)=>{ window.__game.sim.acceptQuest(qid); }, qid);
  await sleep(600);
  const finalLog=await page.evaluate(()=>Object.keys(window.__game.sim.questLog||{}));
  console.log('FINAL LOG', JSON.stringify(finalLog), 'qid=',qid);
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
