const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const before = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  // EXACT skill code
  await page.evaluate(() => { try { window.__game.online.setMoveInput({forward:1, back:1, strafeLeft:1, strafeRight:1, turnLeft:1, turnRight:1, jump:1}); } catch(e){ return 'ERR:'+e.message; } });
  await new Promise(r=>setTimeout(r,2500));
  await page.evaluate(() => { try { window.__game.online.setMoveInput({forward:0, back:0, strafeLeft:0, strafeRight:0, turnLeft:0, turnRight:0, jump:0}); } catch(_){} });
  const after = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z, facing:p.facing}; });
  console.log('FULL setMoveInput moved', Math.hypot(after.x-before.x, after.z-before.z).toFixed(2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
