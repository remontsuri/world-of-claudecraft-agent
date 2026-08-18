const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const ok=await page.evaluate(()=>!!(window.__game&&window.__game.sim)).catch(e=>'ERR:'+e.message);
  console.log('game loaded:', ok);
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
