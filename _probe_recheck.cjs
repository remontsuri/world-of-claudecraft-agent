
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.log('NO GAME TAB'); await browser.disconnect(); return; }
  await page.bringToFront();
  try { await page.waitForFunction('!!window.__game && !!window.__game.sim && !!window.__game.sim.player', { timeout: 30000 }); }
  catch(e){ console.log('WAIT TIMEOUT'); await browser.disconnect(); return; }
  const meta = await page.evaluate(() => ({ account: window.__game.account ? window.__game.account.username : null, dead: !!window.__game.sim.player.dead, hasOnline: !!window.__game.online }));
  const before = await page.evaluate(() => [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z)]);
  await page.evaluate(async () => { const g=window.__game; try{g.controller.stop();}catch(_){} for(let i=0;i<10;i++){try{g.controller.move({forward:true});}catch(_){} await new Promise(r=>setTimeout(r,150));} });
  const after = await page.evaluate(() => [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z)]);
  const k0 = await page.evaluate(()=>{const s=window.__game.sim;return (s.deedStats&&s.deedStats.counters&&s.deedStats.counters.kills)||s.player.kills||0;});
  await page.evaluate(()=>{const g=window.__game,sim=g.sim;let b=null,bd=Infinity;for(const e of sim.entities.values()){if(e.kind!=='mob'||e.dead||(e.hp??0)<=0)continue;const dx=e.pos.x-sim.player.pos.x,dz=e.pos.z-sim.player.pos.z,d=Math.hypot(dx,dz);if(d<=45&&d<bd){bd=d;b=e;}}try{if(b)sim.targetEntity(b.id);else sim.tabTarget();}catch(_){}try{sim.startAutoAttack();}catch(_){}});
  await new Promise(r=>setTimeout(r,2500));
  const k1 = await page.evaluate(()=>{const s=window.__game.sim;return (s.deedStats&&s.deedStats.counters&&s.deedStats.counters.kills)||s.player.kills||0;});
  console.log(JSON.stringify({meta, before, after, moved: before[0]!==after[0]||before[1]!==after[1], kills_before:k0, kills_after:k1, attackWorked:k1!==k0}, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
