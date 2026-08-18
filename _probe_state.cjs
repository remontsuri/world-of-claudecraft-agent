const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';
(async () => {
  const browser = await connect({ browserURL: CDP });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const s = await page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    return {
      dead: !!p.dead, hp: p.hp, maxHp: p.maxHp, level: p.level,
      online_setMoveInput: typeof (g.online && g.online.setMoveInput),
      online_exists: !!g.online,
      inCombat: !!p.inCombat,
      controller_move: typeof (g.controller && g.controller.move),
      entities: sim.entities.size,
      // is window.__game the live one or a stale object?
      game_id: g.id || (g.constructor && g.constructor.name) || 'n/a',
    };
  });
  console.log(JSON.stringify(s, null, 2));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
