const puppeteer = require('puppeteer-core');
const http = require('http');
function gj(u){return new Promise((r,j)=>{http.get(u,x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>r(JSON.parse(d)));}).on('error',j);});}
(async()=>{
  const v=await gj('http://127.0.0.1:9222/json/version');
  const b=await puppeteer.connect({browserWSEndpoint:v.webSocketDebuggerUrl});
  const p=(await b.pages()).find(x=>x.url().includes('worldofclaudecraft'))||null;
  const s=await p.evaluate(()=>{
    const sim=window.__game.sim;
    return {
      hasSimCounters: !!sim.counters,
      simCounters: sim.counters ? {kills:sim.counters.kills, damage:sim.counters.damageDealt, deaths:sim.counters.deaths} : 'UNDEFINED',
      hasDeedStats: !!sim.deedStats,
      deedStats: sim.deedStats ? {kills:sim.deedStats.counters.kills, damage:sim.deedStats.counters.damageDealt, deaths:sim.deedStats.counters.deaths} : 'UNDEFINED',
    };
  });
  console.log(JSON.stringify(s,null,2));
  await b.disconnect();
})().catch(e=>{console.error(e.message);process.exit(1);});
