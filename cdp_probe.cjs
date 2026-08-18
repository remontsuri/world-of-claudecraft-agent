// read-only probe: confirm window.__game.sim is readable in the live online tab.
const { connect } = require('puppeteer-core');
const CDP = 'http://127.0.0.1:9222';

(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.log('NO GAME TAB'); await browser.disconnect(); return; }
  await page.bringToFront();
  try {
    await page.waitForFunction('!!window.__game && !!window.__game.sim && !!window.__game.sim.player', { timeout: 30000 });
  } catch (e) {
    console.log('TIMEOUT waiting for window.__game.sim'); await browser.disconnect(); return;
  }
  const snap = await page.evaluate(() => {
    const g = window.__game, sim = g.sim, p = sim.player;
    const ents = [];
    for (const e of sim.entities.values()) {
      if (e.pos) ents.push({ kind: e.kind, name: e.name, x: Math.round(e.pos.x), z: Math.round(e.pos.z), hp: e.hp, hostile: !!e.hostile, dead: !!e.dead });
    }
    return {
      account: g.account ? g.account.username : 'NONE',
      player: { x: Math.round(p.pos.x), z: Math.round(p.pos.z), hp: p.hp, maxHp: p.maxHp,
                level: p.level, dead: !!p.dead, facing: p.facing },
      quests: (g.online && g.online.quests) ? g.online.quests : (sim.quests || null),
      copper: sim.copper,
      n_entities: ents.length,
      sample_entities: ents.slice(0, 8),
    };
  });
  console.log(JSON.stringify(snap, null, 2));
  await browser.disconnect();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
