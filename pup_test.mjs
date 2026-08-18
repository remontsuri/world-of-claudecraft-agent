import { connect } from 'puppeteer-core';
const CDP = 'http://127.0.0.1:9222';

async function main() {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.log('NO GAME TAB'); await browser.disconnect(); return; }
  console.log('tab:', (typeof page.url === 'function') ? page.url() : page.url);
  await page.bringToFront();
  // read start pos
  const p0 = await page.evaluate('JSON.stringify(window.__game.sim.player.pos)');
  console.log('start:', p0);
  // hold W 5s (as in smoke_browser.mjs)
  await page.keyboard.down('w');
  await new Promise(r => setTimeout(r, 5000));
  await page.keyboard.up('w');
  const p1 = await page.evaluate('JSON.stringify(window.__game.sim.player.pos)');
  console.log('after W:', p1);
  const a = JSON.parse(p0), b = JSON.parse(p1);
  const d = Math.hypot(b.x-a.x, b.z-a.z);
  console.log('moved:', d.toFixed(1), d > 10 ? 'OK' : 'FAIL');
  await browser.disconnect();
}
main().catch(e => { console.error(e); process.exit(1); });
