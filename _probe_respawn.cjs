const { connect } = require('puppeteer-core');
const http = require('http');
const CDP = 'http://127.0.0.1:9222';
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
  const r = await postJson(BRIDGE+'/respawn', {});
  console.log('bridge respawn:', JSON.stringify(r).slice(0,150));
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  await new Promise(r=>setTimeout(r,2000));
  const s = await page.evaluate(() => { const p = window.__game.sim.player; return { dead: !!p.dead, hp: p.hp, maxHp: p.maxHp }; });
  console.log('after respawn:', JSON.stringify(s));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
