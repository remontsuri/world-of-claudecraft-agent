const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const c=window.__game.controller;
    const out={ctrlProto:Object.getOwnPropertyNames(Object.getPrototypeOf(c)||{})};
    // move arg shape
    out.moveDoc = c.move ? c.move.toString().slice(0,200) : 'no move';
    // player facing field
    const p=window.__game.sim.player;
    out.facingType = typeof p.facing;
    out.posSample = p.pos? {x:Math.round(p.pos.x),z:Math.round(p.pos.z)}:null;
    // is there a 'face' or 'faceTo' on controller or sim?
    out.simFace = Object.keys(window.__game.sim).filter(k=>/face|look|turn|rotate/i.test(k));
    return out;
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
