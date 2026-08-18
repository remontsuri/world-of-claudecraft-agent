const pptr = require('puppeteer-core');
const http = require('http');

function get(url){return new Promise((res,rej)=>{http.get(url,r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>res(d));}).on('error',rej);});}

(async()=>{
  const ver = JSON.parse(await get('http://127.0.0.1:9222/json/version'));
  const browser = await pptr.connect({ browserWSEndpoint: ver.webSocketDebuggerUrl });
  const pages = await browser.pages();
  const page = pages.find(p=>/worldofclaudecraft|localhost|game/i.test(p.url()||'')) || pages[0];
  const ev = (expr)=>page.evaluate(expr);
  const pos = ()=>ev(`(window.__game&&window.__game.sim&&window.__game.sim.player)?({x:window.__game.sim.player.pos.x,y:window.__game.sim.player.pos.y,z:window.__game.sim.player.pos.z}):null`);
  const before = await pos();

  const api = await ev(`(function(){
    var g=window.__game; if(!g) return {noGame:true};
    var out={hasSim:!!g.sim};
    try{ out.ctrlProto=Object.getOwnPropertyNames(Object.getPrototypeOf(g.controller||{})||{}); }catch(e){ out.ctrlErr=String(e);}    
    try{ out.simKeys=Object.getOwnPropertyNames(g.sim||{}).slice(0,80); }catch(e){}
    try{ out.movementKeys=g.sim&&g.sim.movement?Object.getOwnPropertyNames(g.sim.movement):null; }catch(e){}
    try{ out.input=g.sim&&g.sim.input?{enabled:g.sim.input.enabled, suspend:g.sim.input.suspendMovement}:null; }catch(e){}
    try{ out.playerKeys=g.sim&&g.sim.player?Object.getOwnPropertyNames(g.sim.player).slice(0,80):null; }catch(e){}
    return out;
  })()`);

  async function tryMove(expr,label){
    const p1 = await pos();
    try{ await ev(expr); }catch(e){}
    await new Promise(r=>setTimeout(r,1600));
    const p2 = await pos();
    const delta = (p1&&p2)?Math.hypot(p2.x-p1.x, p2.z-p1.z):null;
    return {label, before:p1, after:p2, delta};
  }

  const results = [];
  results.push(await tryMove(`(window.__game.controller&&window.__game.controller.move)?window.__game.controller.move({forward:true}):null`, 'controller.move(fwd)'));
  results.push(await tryMove(`(window.__game.sim&&window.__game.sim.movement&&window.__game.sim.movement.setInput)?window.__game.sim.movement.setInput({forward:1}):null`, 'sim.movement.setInput'));
  results.push(await tryMove(`(window.__game.sim&&window.__game.sim.player&&window.__game.sim.player.setMoveInput)?window.__game.sim.player.setMoveInput({forward:1}):null`, 'player.setMoveInput'));
  results.push(await tryMove(`(window.__game.sim&&window.__game.sim.player&&window.__game.sim.player.moveInput)?(window.__game.sim.player.moveInput={forward:1},true):null`, 'player.moveInput='));
  // keyboard via CDP page focus
  await page.bringToFront();
  await page.mouse.click(640,360);
  results.push(await tryMove(`()=>{window.dispatchEvent(new KeyboardEvent('keydown',{key:'w',code:'KeyW',keyCode:87,which:87,bubbles:true}));return true;}`, 'synthetic keydown w'));

  console.log('API:', JSON.stringify(api,null,1));
  console.log('BEFORE:', JSON.stringify(before));
  console.log('MOVES:', JSON.stringify(results,null,1));
  await browser.disconnect();
})().catch(e=>{console.error('FATAL',e);process.exit(1);});
