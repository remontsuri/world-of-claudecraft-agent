const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const before = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  // real keyboard 'w' hold via CDP
  await page.keyboard.down('w');
  await new Promise(r=>setTimeout(r,2500));
  await page.keyboard.up('w');
  const after = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  console.log('KEYBOARD w moved', Math.hypot(after.x-before.x, after.z-before.z).toFixed(2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
