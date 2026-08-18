const pptr=require('puppeteer-core');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const pos0=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z)}));
  // TEST 1: controller.move
  await page.evaluate(()=>{ const c=window.__game.controller; if(c&&c.stop)c.stop(); if(c&&c.move)c.move({forward:true}); });
  await sleep(1500);
  await page.evaluate(()=>{ const c=window.__game.controller; if(c&&c.stop)c.stop(); });
  const pos1=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z)}));
  const dCtl=Math.round(Math.hypot(pos1.x-pos0.x,pos1.z-pos0.z));
  // TEST 2: keyboard.down('w')
  await page.keyboard.down('w');
  await sleep(1500);
  await page.keyboard.up('w');
  const pos2=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z)}));
  const dKey=Math.round(Math.hypot(pos2.x-pos1.x,pos2.z-pos1.z));
  console.log(JSON.stringify({pos0,pos1,pos2,dist_controller:dCtl,dist_keyboard:dKey}));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
