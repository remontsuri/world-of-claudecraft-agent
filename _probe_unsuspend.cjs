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
      inputMethods: g.input ? Object.getOwnPropertyNames(Object.getPrototypeOf(g.input)).filter(k=>typeof g.input[k]==='function') : [],
      inputHasSuspendSetter: g.input ? Object.getOwnPropertyDescriptor(g.input,'suspendMovement') : 'n/a',
      controllerStop: typeof (g.controller && g.controller.stop),
      controllerEnabled: g.controller ? g.controller.enabled : 'n/a',
    };
  });
  console.log(JSON.stringify(info, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
