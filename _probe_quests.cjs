
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.log('NO GAME TAB'); await browser.disconnect(); return; }
  await page.bringToFront();
  try { await page.waitForFunction('!!window.__game && !!window.__game.sim', { timeout: 20000 }); }
  catch(e){ console.log('WAIT TIMEOUT'); await browser.disconnect(); return; }
  const out = await page.evaluate(() => {
    const g = window.__game, sim = g.sim;
    const res = {};
    // 1) online.quests shape
    res.online_keys = g.online ? Object.keys(g.online) : 'no-online';
    res.online_quests = g.online && g.online.quests ? (Array.isArray(g.online.quests) ? g.online.quests.length : typeof g.online.quests) : 'none';
    // 2) sim.questLog
    res.questLog_isArray = Array.isArray(sim.questLog);
    res.questLog_len = sim.questLog ? sim.questLog.length : 0;
    if (Array.isArray(sim.questLog) && sim.questLog.length) {
      const q = sim.questLog[0];
      res.questLog_sample_keys = Object.keys(q).slice(0,30);
      res.questLog_sample = JSON.parse(JSON.stringify(q)).toString ? null : null;
    }
    // 3) NPC entities with any quest-like fields
    const npcs = [];
    for (const e of sim.entities.values()) {
      if (e.kind === 'npc' || e.type === 'npc') {
        const qids = e.questIds || e.questId || e.offeredQuests || e.questOffers;
        if (qids) npcs.push({ name: e.name, qids });
      }
    }
    res.npcs_with_quest_fields = npcs.slice(0,5);
    // 4) Does sim expose a method to get available quests?
    res.sim_quest_methods = Object.getOwnPropertyNames(sim).filter(k => /quest/i.test(k)).slice(0,30);
    return res;
  });
  console.log(JSON.stringify(out, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
