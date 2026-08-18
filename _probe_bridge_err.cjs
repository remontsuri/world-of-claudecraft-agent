const { connect } = require('puppeteer-core');
const http = require('http');
const CDP = 'http://127.0.0.1:9222';
const BRIDGE = 'http://127.0.0.1:8791';
function postJson(url, body) {
  return new Promise((res, rej) => {
    const data = JSON.stringify(body || {});
    const u = new URL(url);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname, method:'POST', headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)} },
      (r)=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>{try{res(JSON.parse(d))}catch(e){rej(e)}});});
    req.on('error',rej);req.write(data);req.end();
  });
}
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // Replicate the EXACT bridge snapshot() body to see which line throws
  const diag = await page.evaluate(() => {
    try {
      const g = window.__game, sim = g.sim, p = sim.player;
      const playerExists = !!p;
      const playerPos = p ? (p.pos ? [p.pos.x, p.pos.z] : 'no pos') : 'no player';
      // what does the bridge's nearby loop see?
      const nearby=[];
      if (p && p.pos) {
        for (const e of sim.entities.values()) {
          if (!e.pos) continue;
          const dx=e.pos.x-p.pos.x, dz=e.pos.z-p.pos.z, d=Math.hypot(dx,dz);
          if (d>70) continue;
          nearby.push({kind:e.kind,name:e.name});
        }
      }
      return { playerExists, playerPos, nearbyCount: nearby.length, sample: nearby.slice(0,3) };
    } catch(e) { return { THREW: e.message, stack: (e.stack||'').slice(0,300) }; }
  });
  console.log('DIRECT EVAL:', JSON.stringify(diag, null, 2));
  // Now via bridge
  const r = await postJson(BRIDGE+'/snapshot', {});
  console.log('BRIDGE:', JSON.stringify(r).slice(0,300));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
