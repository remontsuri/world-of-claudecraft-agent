const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  const pages = await browser.pages();
  console.log('TABS:', pages.map(p => { const u=(typeof p.url==='function')?p.url():(p.url||''); return u.slice(0,50); }));
  let page=null;
  for (const p of pages){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  if(!page){ console.log('NO GAME TAB'); await browser.disconnect(); return; }
  await page.bringToFront();
  try { await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:8000}); console.log('GAME READY'); }
  catch(e){ console.log('NO __game yet'); }
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
