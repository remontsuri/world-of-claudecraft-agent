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
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) { const u=(typeof p.url==='function')?p.url():(p.url||''); if(u.includes('worldofclaudecraft')){page=p;break;} }
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', { timeout: 15000 });
  const before = await page.evaluate(() => {
    const g=window.__game,sim=g.sim,p=sim.player; let best=null,bd=Infinity;
    for(const e of sim.entities.values()){if(e.kind!=='mob'||e.dead||(e.hp??0)<=0)continue;const dx=e.pos.x-p.pos.x,dz=e.pos.z-p.pos.z,d=Math.hypot(dx,dz);if(d<=45&&d<bd){bd=d;best=e;}}
    return best?{id:best.id,hp:best.hp}:null;
  });
  console.log('BEFORE:', JSON.stringify(before));
  const r = await postJson(BRIDGE+'/action', { action:'step', idx:0 });
  console.log('BRIDGE resp ok=', r.ok);
  await new Promise(r=>setTimeout(r,4000));
  const after = await page.evaluate((id)=>{const e=window.__game.sim.entities.get(id);return e?{hp:e.hp,dead:!!e.dead}:{gone:true};}, before.id);
  console.log('AFTER:', JSON.stringify(after), 'DAMAGE=', after.hp!=='gone' && after.hp<before.hp);
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
