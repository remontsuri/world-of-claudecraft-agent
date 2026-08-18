const puppeteer = require('puppeteer-core');
const http = require('http');
function getJSON(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let d=''; r.on('data',c=>d+=c); r.on('end',()=>res(JSON.parse(d))); }).on('error', rej);
  });
}
(async () => {
  const ver = await getJSON('http://127.0.0.1:9222/json/version');
  const browser = await puppeteer.connect({ browserWSEndpoint: ver.webSocketDebuggerUrl });
  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes('worldofclaudecraft')) || pages[0];
  const info = await page.evaluate(() => {
    const g = window.__game;
    const out = { hasGame: !!g, url: location.href };
    if (g) {
      out.simKeys = Object.keys(g.sim || {}).filter(k => /target|nearest|enemy/i.test(k));
      out.gameKeys = Object.keys(g).filter(k => /target|nearest|enemy/i.test(k));
      out.controllerKeys = Object.keys(g.controller || {}).filter(k => /target|nearest|attack|move|interact/i.test(k));
      try { out.simProto = Object.getOwnPropertyNames(Object.getPrototypeOf(g.sim || {})).filter(k => /target|nearest/i.test(k)); } catch(e){ out.simProtoErr = e.message; }
      out.trySimTargetNearestEnemy = typeof g.sim.targetNearestEnemy;
      out.trySimTargetNearest = typeof g.sim.targetNearest;
      out.tryGameTargetNearestEnemy = typeof g.targetNearestEnemy;
    }
    return out;
  });
  console.log(JSON.stringify(info, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
