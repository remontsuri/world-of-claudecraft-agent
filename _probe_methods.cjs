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
  await page.waitForFunction('!!window.__game && !!window.__game.sim', { timeout: 15000 });
  const out = await page.evaluate(() => {
    const sim = window.__game.sim, p = sim.player;
    const simMethods = Object.getOwnPropertyNames(Object.getPrototypeOf(sim)).filter(k => /target|attack|ability|cast|swing|hit|damage|combat/i.test(k));
    const ctrlMethods = Object.getOwnPropertyNames(Object.getPrototypeOf(window.__game.controller)).filter(k => /move|attack|cast|use|interact|target/i.test(k));
    // is there a current target?
    const tgt = p.target || p.currentTarget || p.attackTarget;
    return {
      sim_combat_methods: simMethods,
      controller_methods: ctrlMethods,
      has_target_after_start: !!(p.target || p.currentTarget),
      player_has_weapon: !!(p.equipment && (p.equipment.mainHand || p.equipment[0])),
      player_inRangeInfo: p.rangeInfo || null,
      autoAttack_method_exists: typeof sim.startAutoAttack,
      stopAutoAttack_exists: typeof sim.stopAutoAttack,
    };
  });
  console.log(JSON.stringify(out, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
