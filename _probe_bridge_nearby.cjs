const http = require('http');
const BRIDGE = 'http://127.0.0.1:8791';
function postJson(url, body) {
  return new Promise((res, rej) => {
    const data = JSON.stringify(body || {});
    const u = new URL(url);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST', headers: { 'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)} },
      (r)=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>{try{res(JSON.parse(d))}catch(e){rej(e)}});});
    req.on('error',rej);req.write(data);req.end();
  });
}
(async () => {
  const r = await postJson(BRIDGE+'/snapshot', {});
  const info = r.info || {};
  const nearby = info.nearby || [];
  console.log('nearby count:', nearby.length);
  const npcs = nearby.filter(n => n.kind === 'npc');
  console.log('npc count:', npcs.length);
  console.log('sample npc fields:', npcs.slice(0,3).map(n => ({ name:n.name, questIds:n.questIds, has_q: !!n.questIds })));
  // also dump raw from the live tab to compare
  const { connect } = require('puppeteer-core');
  const browser = await connect({ browserURL: 'http://127.0.0.1:9222' });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const raw = await page.evaluate(() => {
    const sim = window.__game.sim; const out=[];
    for (const e of sim.entities.values()) {
      if (e.kind === 'npc') out.push({ name:e.name, questIds: e.questIds||null, questId: e.questId||null, keys: Object.keys(e).filter(k=>/quest/i.test(k)) });
    }
    return out.slice(0,6);
  });
  console.log('RAW tab npc quest fields:', JSON.stringify(raw, null, 1));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
