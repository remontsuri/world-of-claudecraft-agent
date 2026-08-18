const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // Try to apply lethal damage: set player.hp = 0 then see if combat/kill triggers
  const before = await page.evaluate(() => {
    const p = window.__game.sim.player;
    const f = Object.keys(p).filter(k => /dead|ghost|hp|health|alive|state|spirit|corpse/i.test(k));
    return { fields: f, hp: p.hp, dead: p.dead };
  });
  console.log('PLAYER FIELDS:', JSON.stringify(before));
  // attempt: damage to 0
  const r = await page.evaluate(() => {
    try {
      const p = window.__game.sim.player;
      p.hp = 0;
      if (typeof p.takeDamage === 'function') { p.takeDamage(99999, {source:'debug'}); return 'takeDamage ok'; }
      if (typeof window.__game.sim.applyDamage === 'function') { window.__game.sim.applyDamage(p.id, 99999); return 'applyDamage ok'; }
      return 'no damage method, set hp=0 only';
    } catch(e){ return 'ERR:'+e.message; }
  });
  console.log('KILL ATTEMPT:', r);
  await new Promise(res=>setTimeout(res,1500));
  const after = await page.evaluate(() => {
    const p = window.__game.sim.player;
    return { hp: p.hp, dead: p.dead, ghost: p.ghost, suspendMovement: window.__game.input ? window.__game.input.suspendMovement : 'n/a' };
  });
  console.log('AFTER:', JSON.stringify(after));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
