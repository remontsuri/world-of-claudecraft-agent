const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await browser.pages();
  const page = pages.find(p => p.url().includes('worldofclaudecraft.com')) || pages[0];
  const s = await page.evaluate(() => {
    const g = window.__game; const sim = g.sim; const p = sim.player;
    const out = {};
    out.hasFindPlayerPath = typeof sim.findPlayerPath;
    out.hasResolveDest = typeof sim.resolvePlayerDestination;
    // try a real pathfind from player to a vendor-like point
    try {
      const npcs = [...sim.entities.values()].filter(e => e.kind === 'npc');
      out.npcCount = npcs.length;
      out.npcSample = npcs.slice(0, 3).map(e => ({ name: e.name, x: e.pos.x, z: e.pos.z }));
      if (npcs.length) {
        const tgt = npcs[0];
        const path = sim.findPlayerPath(sim.cfg.seed, p.pos, { x: tgt.pos.x, z: tgt.pos.z }, undefined);
        out.pathType = Array.isArray(path) ? 'array' : typeof path;
        out.pathLen = Array.isArray(path) ? path.length : -1;
        out.pathHead = Array.isArray(path) && path.length ? JSON.stringify(path[0]) : null;
      }
    } catch (e) {
      out.pathErr = e.message;
    }
    return out;
  });
  console.log(JSON.stringify(s, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
