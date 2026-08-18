const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const keys=['__game','game','WOC_OBS','WOC','sim'];
    const found={};
    for(const k of keys){ try{ found[k]= typeof window[k]; }catch(e){ found[k]='err'; } }
    // also scan for any global containing WOC_OBS
    let anyWOC=null;
    try{ for(const k of Object.keys(window)){ if(k.includes('WOC')||k.includes('game')){ anyWOC=anyWOC||k; } } }catch(e){}
    return {found, anyWOClike:anyWOC};
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
