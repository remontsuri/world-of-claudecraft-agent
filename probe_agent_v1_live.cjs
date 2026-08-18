const pptr = require('puppeteer-core');
const http = require('http');
const fs = require('fs');
function get(u){return new Promise((r,j)=>{http.get(u,x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>r(d));}).on('error',j);});}
(async()=>{
  const v = JSON.parse(await get('http://127.0.0.1:9222/json/version'));
  const b = await pptr.connect({browserWSEndpoint:v.webSocketDebuggerUrl});
  const pages = await b.pages();
  const page = pages.find(p=>/worldofclaudecraft|localhost|game/i.test(p.url()||'')) || pages[0];
  const code = fs.readFileSync('dist-tools/agent_v1.iife.js','utf8');
  await page.addScriptTag({ content: code });
  const ready = await page.evaluate(()=> typeof window.__agentV1 === 'object');
  if(!ready){ console.log('INJECT_FAIL'); await b.disconnect(); process.exit(1); }

  const caps = await page.evaluate(()=> window.__agentV1.capabilities());
  const ws = await page.evaluate(()=> window.__agentV1.worldState());
  // вызываем step() один раз (не цикл — не мешаем B1)
  const stepRes = await page.evaluate(()=> window.__agentV1.step());

  console.log('READY:', ready);
  console.log('CAPS:', JSON.stringify(caps.map(c=>({name:c.name,supported:c.supported,ops:c.operations.length}))));
  console.log('WORLD_STATE:', JSON.stringify({
    player: ws.player,
    copper: ws.player && ws.player.copper,
    questsActive: ws.quests && ws.quests.active && ws.quests.active.length,
    questsDone: ws.quests && ws.quests.done && ws.quests.done.length,
    invItems: ws.inventory && ws.inventory.items && ws.inventory.items.length,
    junk: ws.inventory && ws.inventory.items && ws.inventory.items.filter(i=>i.quality===0).length,
    nearbyGivers: ws.nearby && ws.nearby.filter(o=>o.type==='giver').length,
    nearbyVendors: ws.nearby && ws.nearby.filter(o=>o.type==='vendor').length,
    nearbyNodes: ws.nearby && ws.nearby.filter(o=>o.type==='node').length,
    nearbyHostile: ws.nearby && ws.nearby.filter(o=>o.type==='hostile').length,
  }, null, 1));
  console.log('STEP_RESULT:', JSON.stringify(stepRes));
  await b.disconnect();
})().catch(e=>{console.error('FATAL',e);process.exit(1);});
