const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
async function moveOnce(page) {
  const b = await page.evaluate(() => { const p=window.__game.sim.player; return [p.pos.x,p.pos.z]; });
  await page.evaluate(() => { try { window.__game.controller.stop(); window.__game.controller.move({forward:true}); } catch(e){} });
  await new Promise(r=>setTimeout(r,1500));
  await page.evaluate(() => { try { window.__game.controller.stop(); } catch(_){} });
  const a = await page.evaluate(() => { const p=window.__game.sim.player; return [p.pos.x,p.pos.z]; });
  return Math.hypot(a[0]-b[0],a[1]-b[1]);
}
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  // A) baseline: move with suspendMovement=false (default)
  const a = await moveOnce(page);
  console.log('A) suspendMovement=false (baseline): moved', a.toFixed(2));
  // B) set suspendMovement=true, then try to move
  await page.evaluate(() => { window.__game.input.suspendMovement = true; });
  const b = await moveOnce(page);
  console.log('B) suspendMovement=true: moved', b.toFixed(2));
  // C) clear it, then move again
  await page.evaluate(() => { window.__game.input.suspendMovement = false; });
  const c = await moveOnce(page);
  console.log('C) suspendMovement=false (after clear): moved', c.toFixed(2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
