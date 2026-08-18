const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const f = await page.evaluate(() => ({ hidden: document.hidden, hasFocus: document.hasFocus(), visibility: document.visibilityState }));
  console.log('FOCUS', JSON.stringify(f));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
