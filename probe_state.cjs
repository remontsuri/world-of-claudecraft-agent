const pptr=require('puppeteer-core');
(async()=>{
  const b=await pptr.connect({browserURL:'http://127.0.0.1:9222',defaultViewport:null});
  const pages=await b.pages();
  const page=pages.find(p=>/worldofclaudecraft/i.test(p.url()));
  const r=await page.evaluate(()=>{
    const sim=window.__game.sim, p=sim.player;
    return {dead:p.dead, hp:p.hp, hasPos:!!p.pos, inCombat:p.inCombat, autoAttack:p.autoAttack,
      menuOpen: !!window.__game.ui?.menuOpen,
      activeEl: document.activeElement?.tagName,
      bodyFocus: document.activeElement===document.body};
  });
  console.log(JSON.stringify(r,null,1));
  await b.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
