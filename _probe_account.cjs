const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.log('NO_GAME_TAB'); await browser.disconnect(); return; }
  await page.bringToFront();
  try { await page.waitForFunction('!!window.__game && !!window.__game.sim', { timeout: 15000 }); }
  catch(e){ console.log('NO __game'); await browser.disconnect(); return; }
  const out = await page.evaluate(() => {
    const g = window.__game;
    return {
      has_account: !!g.account,
      account_type: g.account ? typeof g.account : null,
      account_keys: g.account ? Object.keys(g.account).slice(0,40) : null,
      account_id: g.account && g.account.id ? g.account.id : null,
      is_logged_in: g.account ? g.account.id || g.account.loggedIn || g.account.username || true : false,
      sim_player_id: g.sim && g.sim.player ? g.sim.player.id : null,
      online_playerId: g.online ? g.online.playerId : null,
      online_ownPlayerId: g.online ? g.online.ownPlayerId : null,
    };
  });
  console.log(JSON.stringify(out, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
