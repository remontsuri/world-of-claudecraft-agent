const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const info = await page.evaluate(() => {
    const g = window.__game;
    return {
      hasInput: !!g.input,
      inputKeys: g.input ? Object.keys(g.input).slice(0,20) : [],
      inputForward: g.input ? g.input.forward : 'n/a',
      onlineSetMove: typeof (g.online && g.online.setMoveInput),
      inputEnabled: g.input ? g.input.enabled : 'n/a',
    };
  });
  console.log('INPUT', JSON.stringify(info));
  // set g.input.forward = true directly
  const before = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  await page.evaluate(() => { window.__game.input.forward = true; });
  await new Promise(r=>setTimeout(r,2500));
  await page.evaluate(() => { window.__game.input.forward = false; });
  const after = await page.evaluate(() => { const p=window.__game.sim.player; return {x:p.pos.x,z:p.pos.z}; });
  console.log('g.input.forward moved', Math.hypot(after.x-before.x, after.z-before.z).toFixed(2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
