const puppeteer = require('puppeteer-core');
const http = require('http');
function getJSON(url){return new Promise((res,rej)=>{http.get(url,r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>res(JSON.parse(d)));}).on('error',rej);});}
(async () => {
  const ver = await getJSON('http://127.0.0.1:9222/json/version');
  const browser = await puppeteer.connect({ browserWSEndpoint: ver.webSocketDebuggerUrl });
  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes('worldofclaudecraft')) || pages[0];
  const info = await page.evaluate(() => {
    const g = window.__game;
    const out = {
      keys: Object.keys(g).slice(0, 40),
      inGame: g.inGame,
      isOnline: g.isOnline ?? g.online ?? 'n/a',
      accountKeys: g.account ? Object.keys(g.account) : 'NO account obj',
      worldExists: !!g.world,
      simOnline: g.sim && (g.sim.online !== undefined ? g.sim.online : 'n/a'),
      playerKeys: g.sim && g.sim.player ? Object.keys(g.sim.player).slice(0,30) : 'no player',
    };
    return out;
  });
  console.log(JSON.stringify(info, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
