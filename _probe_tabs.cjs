
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  const pages = await browser.pages();
  const tabs = [];
  for (const p of pages) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (!u.includes('worldofclaudecraft')) continue;
    let info = { url: u };
    try {
      await p.bringToFront();
      await p.waitForFunction('!!window.__game && !!window.__game.sim && !!window.__game.sim.player', { timeout: 15000 });
      info.game = await p.evaluate(() => ({
        account: window.__game.account ? window.__game.account.username : null,
        mode: window.__game.mode,
        dead: !!window.__game.sim.player.dead,
        pos: [Math.round(window.__game.sim.player.pos.x), Math.round(window.__game.sim.player.pos.z)],
        hasQuestLog: Array.isArray(window.__game.sim.questLog),
        questLogLen: window.__game.sim.questLog ? window.__game.sim.questLog.length : 0,
      }));
    } catch(e) { info.error = e.message; }
    tabs.push(info);
  }
  console.log(JSON.stringify({ n_game_tabs: tabs.length, tabs }, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
