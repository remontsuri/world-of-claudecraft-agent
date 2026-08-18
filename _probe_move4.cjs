const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const s = await page.evaluate(() => {
    const g = window.__game, p = g.sim.player;
    const keys = Object.keys(p).filter(k => /move|lock|input|control|can/i.test(k));
    const flags = {};
    for (const k of ['canMove','movementLocked','moveLocked','frozen','stunned','rooted','inputLocked']) flags[k] = p[k];
    return { posFlags: keys, flags, hasKeyboard: !!g.keyboard, kbEnabled: g.keyboard ? g.keyboard.enabled : 'n/a' };
  });
  console.log(JSON.stringify(s, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
