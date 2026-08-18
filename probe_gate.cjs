const pptr = require('puppeteer-core');
const http = require('http');
function get(u){return new Promise((r,j)=>{http.get(u,x=>{let d='';x.on('data',c=>d+=c);x.on('end',()=>r(d));}).on('error',j);});}
(async()=>{
  const v = JSON.parse(await get('http://127.0.0.1:9222/json/version'));
  const b = await pptr.connect({browserWSEndpoint:v.webSocketDebuggerUrl});
  const pages = await b.pages();
  const page = pages.find(p=>/worldofclaudecraft|localhost|game/i.test(p.url()||'')) || pages[0];
  const ev = e=>page.evaluate(e);
  const state = await ev(`(function(){
    var g=window.__game; var out={};
    function keys(o){try{return Object.getOwnPropertyNames(o||{});}catch(e){return [];}}
    out.controllerProto = keys(Object.getPrototypeOf(g.controller||{}));
    out.controllerOwn = keys(g.controller);
    // probe gate surfaces
    out.hud = {};
    try{ out.hud.isModalOpen = g.hud.isModalOpen; }catch(e){}
    try{ out.hud.promptModalOpen = g.hud.promptModalOpen; }catch(e){}
    try{ out.hud.cameraPromptOpen = g.hud.cameraPromptOpen; }catch(e){}
    out.input = {};
    try{ out.input.enabled = g.input.enabled; }catch(e){}
    try{ out.input.suspendMovement = g.input.suspendMovement; }catch(e){}
    try{ out.input.chatComposerFocused = g.input.chatComposerFocused; }catch(e){}
    try{ out.input.chatComposerVisible = g.input.chatComposerVisible; }catch(e){}
    // what is setMoveInput on?
    out.onlineProto = {};
    try{ out.onlineProto = keys(Object.getPrototypeOf(g.online||{})); }catch(e){}
    out.onlineHasSetMoveInput = typeof (g.online && g.online.setMoveInput);
    // sim.moveInput shape
    out.simMoveInput = JSON.stringify(g.sim.moveInput);
    return out;
  })()`);
  console.log(JSON.stringify(state,null,1));
  await b.disconnect();
})().catch(e=>{console.error('FATAL',e);process.exit(1);});
