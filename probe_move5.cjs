const pptr=require('puppeteer-core');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  // inspect input state
  const st=await page.evaluate(()=>{
    const g=window.__game;
    const inp=g.input; // maybe exposed
    return {
      hasInput: !!inp,
      suspend: inp? inp.suspendMovement : 'n/a',
      keysSize: inp? (inp.keys? inp.keys.size : 'n/a') : 'n/a',
      activeEl: document.activeElement?.tagName,
    };
  }).catch(e=>({err:e.message}));
  console.log('state:', JSON.stringify(st));
  // try: focus body, then dispatch keydown with proper code
  const pos0=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z)}));
  await page.evaluate(()=>{
    if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();
    const ev=new KeyboardEvent('keydown',{key:'w',code:'KeyW',keyCode:87,which:87,bubbles:true,cancelable:true});
    window.dispatchEvent(ev);
  });
  await sleep(1500);
  await page.evaluate(()=>{ const ev=new KeyboardEvent('keyup',{key:'w',code:'KeyW',keyCode:87,which:87,bubbles:true}); window.dispatchEvent(ev); });
  const pos1=await page.evaluate(()=>({x:Math.round(window.__game.sim.player.pos.x),z:Math.round(window.__game.sim.player.pos.z)}));
  const d=Math.round(Math.hypot(pos1.x-pos0.x,pos1.z-pos0.z));
  console.log('move test dist=',d, JSON.stringify({pos0,pos1}));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
