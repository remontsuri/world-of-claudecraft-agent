const pptr = require('puppeteer-core');
const http = require('http');
const fs = require('fs');
function get(u){return new Promise((r,j)=>{http.get(u,x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>r(d));}).on('error',j);});}
(async()=>{
  const v = JSON.parse(await get('http://127.0.0.1:9222/json/version'));
  const b = await pptr.connect({browserWSEndpoint:v.webSocketDebuggerUrl});
  const pages = await b.pages();
  const page = pages.find(p=>/worldofclaudecraft|localhost|game/i.test(p.url()||'')) || pages[0];
  // inject the adapter bundle
  const iife = fs.readFileSync('dist-tools/agent_api.iife.js','utf8');
  await page.evaluate(iife);
  const ready = await page.evaluate(()=> !!(window.__agentApi && window.__agentApi.ready && window.__agentApi.ready()));
  if(!ready){ console.log('INJECT_FAIL: __agentApi not present'); await b.disconnect(); process.exit(1); }
  // read-only world state
  const ws = await page.evaluate(()=> window.__agentApi.readWorldState());
  // method surface check (no mutations)
  const surface = await page.evaluate(()=>{
    const a = window.__agentApi;
    const want = ['move','stop','target','attack','castSlot','loot','openQuestDialog','acceptQuest','turnInQuest','sellAllJunk','sellItem','buyItem','useItem','equipItem','openVendor','harvestNode','market','craft','readWorldState','ready'];
    const missing = want.filter(k=> typeof a[k] !== 'function');
    return { missing, methodCount: want.length - missing.length };
  });
  // safe movement call (returns ok; does not assert displacement)
  const mv = await page.evaluate(()=>{ try { return window.__agentApi.move({forward:1}); } catch(e){ return {ok:false,err:String(e)}; } });
  await page.evaluate(()=> window.__agentApi.stop());
  console.log('READY:', ready);
  console.log('SURFACE:', JSON.stringify(surface));
  console.log('MOVE_OK:', JSON.stringify(mv));
  console.log('WORLD_STATE_SUMMARY:', JSON.stringify({
    player: ws.player,
    copper: ws.economy && ws.economy.copper,
    questsActive: ws.quests && ws.quests.active && ws.quests.active.length,
    questsDone: ws.quests && ws.quests.done && ws.quests.done.length,
    junkCount: ws.inventory && ws.inventory.junkCount,
    nearbyVendors: ws.nearby && ws.nearby.vendors && ws.nearby.vendors.length,
    nearbyGivers: ws.nearby && ws.nearby.givers && ws.nearby.givers.length,
    nearbyNodes: ws.nearby && ws.nearby.nodes && ws.nearby.nodes.length,
    hostileInRange: ws.nearby && ws.nearby.hostileMobsInRange && ws.nearby.hostileMobsInRange.length,
  }, null, 1));
  await b.disconnect();
})().catch(e=>{console.error('FATAL',e);process.exit(1);});
