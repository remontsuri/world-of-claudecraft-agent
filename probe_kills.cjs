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
    const sim = g.sim;
    const out = {};
    // hunt for any kill counter
    out.simKeys = Object.keys(sim).filter(k => /kill|death|stat|score|count|combat/i.test(k));
    out.playerKeys = Object.keys(sim.player).filter(k => /kill|death|stat|score|count|combat/i.test(k));
    try { out.simProto = Object.getOwnPropertyNames(Object.getPrototypeOf(sim)).filter(k => /kill|death|stat|count/i.test(k)); } catch(e){ out.simProtoErr=e.message; }
    // try known structures
    out.hasSimCounters = !!sim.counters;
    out.hasSimStats = !!sim.stats;
    out.hasPlayerKills = sim.player && sim.player.kills !== undefined ? sim.player.kills : 'n/a';
    out.hasPlayerDeaths = sim.player && sim.player.deaths !== undefined ? sim.player.deaths : 'n/a';
    // online layer
    out.onlineHasKills = g.online && g.online.kills !== undefined ? g.online.kills : 'n/a';
    return out;
  });
  console.log(JSON.stringify(info, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
