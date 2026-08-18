const http = require('http');
const CDP = 'http://127.0.0.1:8791';
const sleep = ms => new Promise(r => setTimeout(r, ms));

function pj(u, b) {
  return new Promise((res, rej) => {
    const d = JSON.stringify(b || {});
    const uu = new URL(u);
    const r = http.request({ hostname: uu.hostname, port: uu.port, path: uu.pathname, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(d) } },
      (x) => { let s = ''; x.on('data', c => s += c); x.on('end', () => { try { res(JSON.parse(s)); } catch (e) { rej(e); } }); });
    r.on('error', rej); r.write(d); r.end();
  });
}

(async () => {
  console.log('chase started — driving character into mobs until death');
  for (let i = 0; i < 80; i++) {
    const s = await pj(CDP + '/', { action: 'snapshot' });
    const info = s.info || {};
    const p = info.player || {};
    if (p.dead) { console.log(`[chase] DEAD at iter ${i} — stop. Now user should respawn manually.`); break; }
    const near = (info.nearby || []).filter(n => n.kind === 'mob' && !n.looted && (n.hp ?? 1) > 0);
    if (!near.length) { console.log(`[chase] iter ${i}: no mob, explore`); await pj(CDP + '/', { action: 'explore', steps: 5 }); await sleep(1500); continue; }
    // nearest mob
    near.sort((a, b) => (a.dist ?? 1e9) - (b.dist ?? 1e9));
    const m = near[0];
    console.log(`[chase] iter ${i}: hp=${p.hp}/${p.maxHp} -> mob ${m.id}@${m.dist?.toFixed(0)} (${m.x},${m.z})`);
    // walk to mob, then attack
    await pj(CDP + '/', { action: 'navigate', x: m.x, z: m.z, max_steps: 10 });
    await pj(CDP + '/', { action: 'step', idx: 0 });
    await sleep(2000);
  }
  console.log('[chase] done');
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
