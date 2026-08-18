const pptr=require('puppeteer-core');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const pos0=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z)}));
  // dispatch synthetic keydown/keyup on window (game likely listens on window)
  await page.evaluate(()=>{
    const fire=(type)=>{ const ev=new KeyboardEvent(type,{key:'w',code:'KeyW',keyCode:87,which:87,bubbles:true}); window.dispatchEvent(ev); document.dispatchEvent(ev); };
    fire('keydown');
    setTimeout(()=>fire('keyup'), 2000);
  });
  await sleep(2200);
  const pos1=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z)}));
  const d=Math.round(Math.hypot(pos1.x-pos0.x,pos1.z-pos0.z));
  console.log(JSON.stringify({pos0,pos1,dist:d}));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
