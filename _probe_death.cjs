const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // find death-related sim methods
  const methods = await page.evaluate(() => {
    const sim = window.__game.sim;
    const all = Object.getOwnPropertyNames(Object.getPrototypeOf(sim)).concat(Object.keys(sim));
    const death = all.filter(k => /kill|die|damage|death|spirit|respawn|rebirth|revive|release/i.test(k));
    const g = window.__game;
    return {
      deathMethods: death,
      input_enabled: g.input ? g.input.enabled : 'n/a',
      hasDialog: !!(g.hud && (g.hud.dialog || (g.hud.openDialog && g.hud.openDialog()))),
      hasModal: !!document.querySelector('.modal, .death-screen, [class*="death"], [class*="respawn"]'),
    };
  });
  console.log(JSON.stringify(methods, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
