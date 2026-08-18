// _enter4.cjs — click the CENTER gold ИГРАТЬ button (not the hidden nav one)
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('claudecraft')) { page = p; break; }
  }
  if (!page) { console.error('no game tab'); process.exit(2); }
  await page.bringToFront();
  await sleep(1500);
  // find the visible gold play button: a BUTTON whose rect is non-zero and text=ИГРАТЬ,
  // prefer the one inside the launch panel (not the nav hamburger one with 0-rect)
  const clicked = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')].filter(b => /играть/i.test(b.textContent || ''));
    // the real one has a non-zero bounding box
    const visible = btns.filter(b => { const r = b.getBoundingClientRect(); return r.width > 10 && r.height > 10; });
    const target = visible[0] || btns.find(b => { const r = b.getBoundingClientRect(); return r.width > 0; }) || btns[0];
    if (target) { target.click(); return { text: target.textContent.trim().slice(0,20), rect: (()=>{const r=target.getBoundingClientRect();return [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)];})() }; }
    return null;
  });
  console.log('clicked play:', JSON.stringify(clicked));
  await sleep(3000);
  const after = await page.evaluate(() => ({
    url: location.href,
    hasGame: !!window.__game,
    bodySnippet: (document.body.innerText || '').slice(0, 300),
    buttons: [...new Set([...document.querySelectorAll('button,a,[role=button]')].filter(e=>e.offsetParent&&e.textContent.trim()).map(e=>e.textContent.trim().slice(0,30)))].slice(0,25),
  })).catch(e => ({ err: e.message }));
  console.log('AFTER:', JSON.stringify(after, null, 1));
  await browser.disconnect();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
