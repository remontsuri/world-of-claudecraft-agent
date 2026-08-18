const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const s = await page.evaluate(() => {
    const g = window.__game;
    return {
      suspendMovement: g.input ? g.input.suspendMovement : 'n/a',
      input_enabled: g.input ? g.input.enabled : 'n/a',
      canMove: g.sim.player ? g.sim.player.canMove : 'n/a',
      gameState: g.state || g.gameState || 'n/a',
      // is there a 'dead'/'ghost' state on player?
      playerDead: !!g.sim.player.dead,
      playerGhost: g.sim.player.ghost !== undefined ? g.sim.player.ghost : 'n/a',
    };
  });
  console.log('LIVE STATE:', JSON.stringify(s));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
