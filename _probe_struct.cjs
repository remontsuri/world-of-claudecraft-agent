
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

  const structure = await page.evaluate(() => {
    const g = window.__game, sim = g.sim;
    const pkeys = Object.getOwnPropertyNames(g).filter(k=>!['constructor'].includes(k)).slice(0,40);
    const simkeys = Object.getOwnPropertyNames(sim).filter(k=>!['constructor'].includes(k)).slice(0,60);
    return {
      g_keys: pkeys,
      sim_keys: simkeys,
      hasLocalPlayer: !!sim.localPlayer,
      localPlayerSameAsPlayer: sim.localPlayer ? (sim.localPlayer===sim.player) : null,
      hasAccount: !!g.account,
      mode: g.mode,
      controllerKeys: g.controller ? Object.keys(g.controller) : [],
    };
  });

  // Try attack on nearest mob and see if kills change
  const k0 = await page.evaluate(() => {
    const sim = window.__game.sim;
    const c = (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || sim.player.kills || 0;
    return c;
  });
  let atkErr=null;
  try {
    await page.evaluate(() => {
      const g=window.__game, sim=g.sim;
      let best=null,bd=Infinity;
      for (const e of sim.entities.values()){ if(e.kind!=='mob'||e.dead||(e.hp??0)<=0) continue; const dx=e.pos.x-sim.player.pos.x, dz=e.pos.z-sim.player.pos.z, d=Math.hypot(dx,dz); if(d<=45&&d<bd){bd=d;best=e;} }
      try{ if(best) sim.targetEntity(best.id); else sim.tabTarget(); }catch(_){}
      try{ sim.startAutoAttack(); }catch(_){}
    });
  } catch(e){ atkErr=e.message; }
  await new Promise(r=>setTimeout(r,2000));
  const k1 = await page.evaluate(() => {
    const sim = window.__game.sim;
    return (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || sim.player.kills || 0;
  });

  console.log(JSON.stringify({ structure, kills_before:k0, kills_after:k1, attackChangedKills: k1!==k0, atkErr }, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
