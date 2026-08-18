const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // check input.enabled path
  const en = await page.evaluate(() => {
    const g = window.__game;
    return {
      input_enabled: g.input ? g.input.enabled : 'no g.input',
      online_input_enabled: g.online && g.online.input ? g.online.input.enabled : 'no online.input',
      controller_enabled: g.controller && g.controller.enabled !== undefined ? g.controller.enabled : 'n/a',
    };
  });
  console.log('ENABLED', JSON.stringify(en));
  // try controller.move loop (skill's exploreWalk pattern)
  const before = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  for (let i=0;i<20;i++){
    await page.evaluate(() => { try { window.__game.controller.stop(); window.__game.controller.move({forward:true}); } catch(e){ return e.message; } });
    await new Promise(r=>setTimeout(r,100));
  }
  await page.evaluate(() => { try { window.__game.controller.stop(); } catch(_){} });
  const after = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z,facing:p.facing}; });
  console.log('CONTROLLER.LOOP moved', Math.hypot(after.x-before.x, after.z-before.z).toFixed(2), 'facing', after.facing);
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
