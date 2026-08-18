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
  // inspect gameState candidates
  const state = await page.evaluate(() => {
    const g = window.__game;
    const cands = {};
    for (const k of ['state','gameState','phase','mode','status','screen']) {
      if (g[k] !== undefined) cands[k] = g[k];
    }
    return {
      gameStateCands: cands,
      playerDead: g.sim.player.dead,
      playerGhost: g.sim.player.ghost,
      controllerEnabled: g.controller ? g.controller.enabled : 'n/a',
      inputEnabled: g.input ? g.input.enabled : 'n/a',
    };
  });
  console.log('STATE:', JSON.stringify(state));
  // test: set player.dead=true + ghost=true, try move
  await page.evaluate(() => { window.__game.sim.player.dead = true; window.__game.sim.player.ghost = true; });
  const d = await moveOnce(page);
  console.log('D) dead=true,ghost=true: moved', d.toFixed(2));
  await page.evaluate(() => { window.__game.sim.player.dead = false; window.__game.sim.player.ghost = false; });
  const e = await moveOnce(page);
  console.log('E) dead=false,ghost=false: moved', e.toFixed(2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
