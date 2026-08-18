const pptr=require('puppeteer-core');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const samples=[];
  for(let i=0;i<5;i++){
    const p=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z),k:window.__game.sim.deedStats?.counters?.kills}));
    samples.push(p); await sleep(1500);
  }
  console.log(JSON.stringify(samples));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
