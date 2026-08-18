const { connect } = require('puppeteer-core');
const fs = require('fs');
const CDP = 'http://127.0.0.1:9222';
const LOG = 'D:\\world-of-claudecraft\\death_diag.log';
const sleep = ms => new Promise(r => setTimeout(r, ms));

function log(line) {
  const ts = new Date().toISOString().slice(11, 19);
  fs.appendFileSync(LOG, `[${ts}] ${line}\n`);
  console.log(`[${ts}] ${line}`);
}

(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { log('NO GAME TAB'); process.exit(1); }
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', { timeout: 20000 });
  log('diag started; will poll every 2s. Reproduce death now.');

  let lastDead = false;
  for (let i = 0; i < 1800; i++) { // 60 min max
    try {
      const snap = await page.evaluate(() => {
        const g = window.__game, sim = g.sim, p = sim.player;
        // try a real move and measure
        const b = [p.pos.x, p.pos.z];
        try { g.controller.stop(); g.controller.move({ forward: true }); } catch (e) {}
        return { b, p: [p.pos.x, p.pos.z], dead: !!p.dead, ghost: !!p.ghost,
          hp: p.hp, maxHp: p.maxHp, suspend: g.input ? g.input.suspendMovement : 'n/a',
          ctrlEnabled: g.controller ? g.controller.enabled : 'n/a',
          inputEnabled: g.input ? g.input.enabled : 'n/a',
          nearestMob: (() => { let bd = 1e9, id = null; for (const e of sim.entities.values()) { if (e.kind === 'mob' && !e.dead) { const d = Math.hypot(e.pos.x - p.pos.x, e.pos.z - p.pos.z); if (d < bd) { bd = d; id = e.id; } } } return { id, dist: bd }; })() };
      });
      await sleep(1500);
      await page.evaluate(() => { try { window.__game.controller.stop(); } catch (_) {} });
      const after = await page.evaluate(() => { const p = window.__game.sim.player; return [p.pos.x, p.pos.z]; });
      const moved = Math.hypot(after[0] - snap.b[0], after[1] - snap.b[1]);
      const flag = `dead=${snap.dead} ghost=${snap.ghost} hp=${snap.hp}/${snap.maxHp} suspend=${snap.suspend} ctrlEn=${snap.ctrlEnabled} inEn=${snap.inputEnabled} mob=${snap.nearestMob.id}@${snap.nearestMob.dist.toFixed(0)}`;
      log(`moved=${moved.toFixed(2)} | ${flag}`);
      if (snap.dead && !lastDead) log('>>> DEATH DETECTED');
      if (!snap.dead && lastDead) log('>>> RESPAWN DETECTED (player alive again)');
      lastDead = snap.dead;
    } catch (e) {
      log('eval err: ' + e.message);
    }
    await sleep(500);
  }
  await browser.disconnect();
})().catch(e => { log('FATAL ' + e.message); process.exit(1); });
