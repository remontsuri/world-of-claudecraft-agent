// Verifies the EXACT algorithm patched into browser_bridge.cjs freshPage()+snapshot():
//  - pick the FIRST tab whose execution context has a LIVE player (level is a number)
//  - single handle for the whole read (no cross-evaluate desync)
//  - stale-connection reconnect
// Mirrors the bridge code so we prove the fix against the live tab without needing
// the HTTP daemon to stay up (background daemons get killed in this env).
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';

async function freshPage(browser) {
  if (!browser) browser = await connect({ browserURL: CDP });
  let pages;
  try {
    pages = await browser.pages();
  } catch (_) {
    browser = null;
    browser = await connect({ browserURL: CDP });
    pages = await browser.pages();
  }
  for (const p of pages) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (!u.includes('worldofclaudecraft')) continue;
    try {
      const live = await p.evaluate(() =>
        !!(window.__game && window.__game.sim && window.__game.sim.player &&
           typeof window.__game.sim.player.level === 'number'));
      if (live) return p;
    } catch (_) { /* dead context, try next */ }
  }
  return null;
}

(async () => {
  const browser = await connect({ browserURL: CDP });
  const cur = await freshPage(browser);
  if (!cur) { console.log('RESULT: no live game tab found'); process.exit(2); }
  console.error('[verify] picked live tab:', (typeof cur.url === 'function' ? cur.url() : cur.url).slice(0, 50));
  try { await cur.bringToFront(); } catch (_) {}
  const r = await cur.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    const nearby = [];
    for (const e of sim.entities.values()) {
      if (!e.pos) continue;
      const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z;
      if (Math.hypot(dx, dz) > 70) continue;
      nearby.push({ id: e.id, name: e.name, hostile: !!e.hostile });
    }
    let active = 0, ready = 0;
    if (sim.questLog && typeof sim.questLog.forEach === 'function') {
      sim.questLog.forEach((qp) => { if (qp.state === 'active') active++; else if (qp.state === 'ready') ready++; });
    }
    return {
      name: p.name, level: p.level, hp: p.hp, maxHp: p.maxHp, dead: !!p.dead,
      active, ready, nearby: nearby.length, quests_done: p.quests_done || 0,
    };
  });
  console.log('RESULT:', JSON.stringify(r));
  await browser.disconnect();
})().catch((e) => { console.error('VERIFY ERROR:', e.message); process.exit(1); });
