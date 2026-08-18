const pptr=require('puppeteer-core');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim;
    const tele=Object.keys(sim).filter(k=>/teleport|warp|setpos|setPos|moveTo|place/i.test(k));
    const ptele=Object.getOwnPropertyNames(Object.getPrototypeOf(sim.player)||{}).filter(k=>/teleport|warp|setpos|setPos|moveTo|place/i.test(k));
    return {simTele:tele, playerTele:ptele};
  });
  console.log(JSON.stringify(r));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
