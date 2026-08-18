const pptr = require('puppeteer-core');
const http = require('http');
const fs = require('fs');
function get(u){return new Promise((r,j)=>{http.get(u,x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>r(d));}).on('error',j);});}
(async()=>{
  const v = JSON.parse(await get('http://127.0.0.1:9222/json/version'));
  const b = await pptr.connect({browserWSEndpoint:v.webSocketDebuggerUrl});
  const pages = await b.pages();
  const page = pages.find(p=>/worldofclaudecraft|localhost|game/i.test(p.url()||'')) || pages[0];
  const code = fs.readFileSync('dist-tools/agent_api.bundle.js','utf8');
  await page.addScriptTag({ content: code });
  const rawCounts = await page.evaluate(()=>{
    const g=window.__game; const sim=g.sim;
    let total=0, npc=0, mob=0, node=0, hostile=0;
    sim.entities.forEach(e=>{ total++; if(e.kind==='npc')npc++; if(e.kind==='mob')mob++; if(e.nodeType||e.gatherTier!==undefined)node++; if(e.kind==='mob'&&e.hostile&&(e.hp||0)>0)hostile++; });
    return {total, npc, mob, node, hostile, hasQuestLog: !!sim.questLog};
  });
  // also dump a few giver-like npcs if any
  const givers = await page.evaluate(()=>{
    const g=window.__game; const sim=g.sim; const out=[];
    sim.entities.forEach(e=>{ if(e.kind==='npc' && Array.isArray(e.questIds) && e.questIds.length) out.push({id:e.id, name:e.name, questIds:e.questIds}); });
    return out.slice(0,10);
  });
  console.log('RAW_ENTITY_COUNTS:', JSON.stringify(rawCounts));
  console.log('GIVERS:', JSON.stringify(givers));
  await b.disconnect();
})().catch(e=>{console.error('FATAL',e);process.exit(1);});
