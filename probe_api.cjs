const pptr = require('puppeteer-core');
const http = require('http');
function get(u){return new Promise((r,j)=>{http.get(u,x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>r(d));}).on('error',j);});}
(async()=>{
  const v = JSON.parse(await get('http://127.0.0.1:9222/json/version'));
  const b = await pptr.connect({browserWSEndpoint:v.webSocketDebuggerUrl});
  const pages = await b.pages();
  const page = pages.find(p=>/worldofclaudecraft|localhost|game/i.test(p.url()||'')) || pages[0];
  const ev = e=>page.evaluate(e);
  const api = await ev(`(function(){
    var g=window.__game; if(!g) return {noGame:true};
    var out={};
    function keys(o){try{return Object.getOwnPropertyNames(o||{});}catch(e){return [];}}
    out.controllerKeys = keys(g.controller);
    out.gameKeys = keys(g);
    // sim-level capability probes
    out.simHas = {};
    ['sellItem','sellAllJunk','buyItem','craft','craftRecipe','harvestNode','gather','acceptQuest','turnInQuest','completeQuest','openQuestDialog','interact','targetEntity','startAutoAttack','moveInput','moveTo','clickMove','setMoveGoal'].forEach(k=>{
      try{ out.simHas[k] = typeof g.sim[k]; }catch(e){ out.simHas[k]='err'; }
    });
    out.worldApiHas = {};
    try{ var wa = g.worldApi || (g.sim && g.sim.worldApi); out.worldApiType = typeof wa; out.worldApiKeys = keys(wa); }catch(e){}
    // hud
    out.hudHas = {};
    try{ var h=g.hud; out.hudKeys=keys(h); ['openQuestDialog','sellAllJunk','openVendor','openMarket','craft'].forEach(k=>{out.hudHas[k]=typeof (h&&h[k]);}); }catch(e){}
    // controller move goal api
    out.ctrlMoveApi = {};
    ['move','stop','clickMove','moveTo','setMoveGoal','faceAngle','moveToward'].forEach(k=>{ try{out.ctrlMoveApi[k]=typeof g.controller[k];}catch(e){} });
    return out;
  })()`);
  console.log(JSON.stringify(api,null,1));
  await b.disconnect();
})().catch(e=>{console.error('FATAL',e);process.exit(1);});
