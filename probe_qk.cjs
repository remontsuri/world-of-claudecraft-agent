const pptr=require('puppeteer-core');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  // sample nearestHostile over 10s
  let samples=[];
  for(let i=0;i<10;i++){
    const r=await page.evaluate(()=>{
      const sim=window.__game.sim, p=sim.player, pp=p.pos||{};
      let nh=1e9; sim.entities.forEach(e=>{ if(e.kind==='mob'&&!e.dead&&(e.hp??0)>0&&e.hostile){ const ep=e.pos||{}; const d=(pp.x!==undefined&&ep.x!==undefined)?Math.hypot(ep.x-pp.x,ep.z-pp.z):1e9; if(d<nh)nh=d; } });
      return Math.round(nh);
    }).catch(()=>-1);
    samples.push(r); await sleep(1000);
  }
  console.log('nearestHostile samples:', JSON.stringify(samples));
  console.log('maxNearestHostile:', Math.max(...samples), '(glue active if >15)');
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
