const pptr=require('puppeteer-core');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const pos0=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z)}));
  // ensure chat not focused: click canvas
  await page.evaluate(()=>{ const c=document.querySelector('canvas'); if(c) c.focus(); }).catch(()=>{});
  await page.keyboard.down('w');
  await sleep(2000);
  await page.keyboard.up('w');
  const pos1=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z)}));
  const d=Math.round(Math.hypot(pos1.x-pos0.x,pos1.z-pos0.z));
  console.log(JSON.stringify({pos0,pos1,dist:d}));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
