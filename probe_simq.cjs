const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim;
    const keys=Object.keys(sim).filter(k=>/quest/i.test(k));
    const out={questKeys:keys};
    // inspect each
    for(const k of keys){
      try{
        const v=sim[k];
        let t=typeof v;
        if(Array.isArray(v)) t='array('+v.length+')';
        else if(v&&typeof v==='object') t='obj keys:'+Object.keys(v).slice(0,10).join(',');
        out['k_'+k]=t;
      }catch(e){ out['k_'+k]='ERR'; }
    }
    // try questState with various
    try{ out.questStateSrc = sim.questState.toString().slice(0,400); }catch(e){}
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
