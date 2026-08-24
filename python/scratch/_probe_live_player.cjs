// probe: read live window.__game.sim.player directly via CDP, bypassing bridge cache
const { connect } = require('puppeteer-core');
(async () => {
  const browser = await connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await browser.pages();
  const page = pages.find(p => (p.url()||'').includes('worldofclaudecraft')) || pages[0];
  if (!page) { console.log('NO PAGE'); process.exit(1); }
  const info = await page.evaluate(() => {
    const g = window.__game;
    if (!g || !g.sim) return { hasGame: false };
    const p = g.sim.player;
    return {
      hasGame: true,
      name: p && p.name,
      level: p && p.level,
      hp: p && p.hp, maxHp: p && p.maxHp, dead: p && p.dead,
      activeQuests: (g.sim.questLog ? [...g.sim.questLog.values()].filter(q=>q.state==='active').length : 'n/a'),
    };
  }).catch(e => ({ error: e.message }));
  console.log(JSON.stringify(info, null, 2));
  await browser.disconnect();
})();
