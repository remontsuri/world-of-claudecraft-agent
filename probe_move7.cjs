const pptr = require('puppeteer-core');
const http = require('http');
function get(u){return new Promise((r,j)=>{http.get(u,x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>r(d));}).on('error',j);});}
(async()=>{
  const v = JSON.parse(await get('http://127.0.0.1:9222/json/version'));
  const b = await pptr.connect({browserWSEndpoint:v.webSocketDebuggerUrl});
  const pages = await b.pages();
  const page = pages.find(p=>/worldofclaudecraft|localhost|game/i.test(p.url()||'')) || pages[0];
  const ev = e=>page.evaluate(e);
  const pos = ()=>ev(`(window.__game&&window.__game.sim&&window.__game.sim.player)?({x:window.__game.sim.player.pos.x,z:window.__game.sim.player.pos.z}):null`);
  const gate = await ev(`(function(){var g=window.__game;var out={};try{out.gateEnabled=g.gameplayInputGate?g.gameplayInputGate.enabled:undefined;}catch(e){}try{out.inputEnabled=g.input?g.input.enabled:undefined;}catch(e){}try{out.inputSuspend=g.input?g.input.suspendMovement:undefined;}catch(e){}try{out.moveInputType=typeof (g.sim.moveInput);}catch(e){}try{out.moveInputVal=JSON.stringify(g.sim.moveInput);}catch(e){}return out;})()`);
  async function trySet(expr,label){
    const p1=await pos(); try{await ev(expr);}catch(e){} await new Promise(r=>setTimeout(r,1500));
    const p2=await pos(); const d=(p1&&p2)?Math.hypot(p2.x-p1.x,p2.z-p1.z):null;
    return {label,before:p1,after:p2,delta:d};
  }
  const res=[];
  res.push(await trySet(`(window.__game.sim.moveInput={forward:1,back:0,strafeLeft:0,strafeRight:0,turnLeft:0,turnRight:0,jump:false})`,'sim.moveInput={forward:1}'));
  res.push(await trySet(`(window.__game.sim.moveInput.forward=1)`,'sim.moveInput.forward=1'));
  res.push(await trySet(`(window.__game.controller&&window.__game.controller.setMoveInput)?window.__game.controller.setMoveInput({forward:1}):null`,'controller.setMoveInput'));
  res.push(await trySet(`(window.__game.controller&&window.__game.controller.move)?(window.__game.controller.stop(),window.__game.controller.move({forward:true})):null`,'controller.stop+move'));
  // try with gate forced
  const afterGate = await ev(`(function(){var g=window.__game;try{if(g.gameplayInputGate)g.gameplayInputGate.enabled=true;}catch(e){}try{if(g.input){g.input.enabled=true;g.input.suspendMovement=false;}}catch(e){}return true;})()`);
  res.push(await trySet(`(window.__game.sim.moveInput={forward:1})`,'after gate force: sim.moveInput={forward:1}'));
  console.log('GATE:',JSON.stringify(gate));
  console.log('AFTER_GATE_FORCE:',afterGate);
  console.log('RESULTS:',JSON.stringify(res,null,1));
  await b.disconnect();
})().catch(e=>{console.error('FATAL',e);process.exit(1);});
