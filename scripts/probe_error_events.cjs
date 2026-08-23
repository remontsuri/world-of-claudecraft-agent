// Probe (read-only): does sim.drainEvents exist, and does a doomed turnInQuest
// produce an error event? We call drainEvents BEFORE and AFTER the doomed call
// and diff. No game-state mutation beyond what the agent already does every run.
const puppeteer = require('puppeteer-core');

(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await browser.pages();
  let page = null;
  for (const p of pages) {
    const ok = await p.evaluate(() => !!(window.__game && window.__game.sim && window.__game.sim.player))
      .catch(() => false);
    if (ok) { page = p; break; }
  }
  if (!page) { console.log('NO GAME TAB'); process.exit(1); }

  const probe = await page.evaluate(() => {
    const s = window.__game.sim;
    return {
      hasDrain: typeof s.drainEvents,
      hasTurnIn: typeof s.turnInQuest,
      playerPos: s.player ? { x: s.player.pos.x, z: s.player.pos.z } : null,
    };
  });
  console.log('probe:', JSON.stringify(probe));

  // drain before
  await page.evaluate(() => { window.__wocEventsBefore = window.__game.sim.drainEvents(); });
  // doomed turn-in: quest that is ready but we stand far from its NPC
  const res = await page.evaluate(() => {
    const s = window.__game.sim;
    let readyId = null;
    for (const [id, q] of (s.questLog ? s.questLog.entries() : [])) {
      if (q.state === 'ready') { readyId = id; break; }
    }
    if (!readyId) return { skipped: true };
    try { s.turnInQuest(String(readyId)); return { called: readyId }; }
    catch (e) { return { threw: String(e && e.message || e) }; }
  });
  console.log('doomed turnIn:', JSON.stringify(res));
  await new Promise(r => setTimeout(r, 400));
  const after = await page.evaluate(() => {
    const ev = window.__game.sim.drainEvents();
    return ev.filter(e => e.type === 'error').map(e => ({ text: e.text, reason: e.reason }))
      .concat(window.__wocEventsBefore.filter(e => e.type === 'error')
        .map(e => ({ text: '[before]' + e.text })));
  });
  console.log('error events:', JSON.stringify(after));
  await browser.disconnect();
})().catch(e => { console.error('PROBE FAIL', e.message); process.exit(1); });
