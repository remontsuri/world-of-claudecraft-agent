// game_screenshot.cjs — capture the live game tab to a PNG (for visual monitoring)
// Usage: node scripts/game_screenshot.cjs [output.png]
const { connect } = require('puppeteer-core');
const path = require('path');

(async () => {
  const out = process.argv[2] || path.join(__dirname, '..', 'game_screen.png');
  const b = await connect({ browserURL: 'http://127.0.0.1:9222' });
  try {
    const pages = await b.pages();
    for (const p of pages) {
      const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
      if (!u.includes('worldofclaudecraft')) continue;
      // bringToFront so the canvas renders at full rate (background tabs may throttle)
      try { await p.bringToFront(); } catch (_) {}
      await p.screenshot({ path: out });
      console.log('SAVED ' + out);
      return;
    }
    console.log('NO_GAME_TAB');
    process.exitCode = 1;
  } finally {
    await b.disconnect();
  }
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
