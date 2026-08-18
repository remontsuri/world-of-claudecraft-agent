const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const diag = await page.evaluate(() => {
    const g = window.__game, p = g.sim.player;
    return {
      input_enabled: g.input ? g.input.enabled : (g.online && g.online.input ? g.online.input.enabled : 'n/a'),
      moveInput: g.online && g.online.moveInput ? g.online.moveInput : 'n/a',
      facing: p.facing, inCombat: !!p.inCombat,
      // is there a modal/dialog blocking?
      hasDialog: !!(g.hud && g.hud.dialog),
    };
  });
  console.log('DIAG', JSON.stringify(diag));
  // HOLD forward for 2.5s via repeated setMoveInput ticks
  const before = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  for (let i=0;i<25;i++){
    await page.evaluate(() => { try { window.__game.online.setMoveInput({forward:1}); } catch(_){} });
    await new Promise(r=>setTimeout(r,100));
  }
  await page.evaluate(() => { try { window.__game.online.setMoveInput({forward:0}); } catch(_){} });
  const after = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  console.log('HELD moved', Math.hypot(after.x-before.x, after.z-before.z).toFixed(2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
