const puppeteer = require('puppeteer-core');
const http = require('http');
function gj(u){return new Promise((r,j)=>{http.get(u,x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>r(JSON.parse(d)));}).on('error',j);});}
(async()=>{
  const v=await gj('http://127.0.0.1:9222/json/version');
  const b=await puppeteer.connect({browserWSEndpoint:v.webSocketDebuggerUrl});
  const p=(await b.pages()).find(x=>x.url().includes('worldofclaudecraft'))||null;
  const s=await p.evaluate(()=>{
    const g=window.__game, sim=g.sim;
    const out={};
    // deep scan sim for any numeric kill/death-ish field
    const scan=(obj,path,depth)=>{
      if(depth>3||!obj||typeof obj!=='object')return;
      for(const k of Object.keys(obj)){
        const v=obj[k];
        if(/kill|death|slain|murder/i.test(k)&&typeof v==='number') out[path+'.'+k]=v;
        if(typeof v==='object'&&v!==null) scan(v,path+'.'+k,depth+1);
      }
    };
    scan(sim,'sim',0);
    scan(g.online,'online',0);
    scan(g,'g',0);
    // also check combat log array
    out.hasCombatLog = !!(sim.combatLog||sim.combat_log||g.combatLog);
    return out;
  });
  console.log(JSON.stringify(s,null,2));
  await b.disconnect();
})().catch(e=>{console.error(e.message);process.exit(1);});
