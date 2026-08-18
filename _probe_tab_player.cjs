const { connect } = require('puppeteer-core');
(async () => {
  const browser = await connect({ browserURL: 'http://127.0.0.1:9222' });
  let page=null;
  for (const p of await browser.pages()){const u=(typeof p.url==='function')?p.url():(p.url||'');if(u.includes('worldofclaudecraft')){page=p;break;}}
  await page.bringToFront();
  await page.waitForFunction('!!window.__game && !!window.__game.sim', {timeout:15000});
  const out = await page.evaluate(() => {
    const g=window.__game, sim=g.sim;
    return { player_id: sim.player?.id, player_name: sim.player?.name, online_playerId: g.online?.playerId, kills: sim.player?.kills, deaths: sim.player?.deaths, pos:[sim.player?.pos?.x, sim.player?.pos?.z] };
  });
  console.log('TAB:', JSON.stringify(out));
  await browser.disconnect();
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
