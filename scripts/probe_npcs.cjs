// throwaway probe: real NPC positions vs my static table (agent walked to the
// table coords but turn_in said "not nearby" -> table may be stale)
const { connect } = require('puppeteer-core');
(async () => {
  const b = await connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await b.pages();
  for (const p of pages) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (!u.includes('worldofclaudecraft')) continue;
    const d = await p.evaluate(() => {
      const sim = window.__game.sim;
      const want = ['foreman_odell', 'trader_wilkes', 'apothecary_lin', 'marshal_redbrook', 'brother_aldric'];
      const out = {};
      for (const e of sim.entities.values()) {
        if (e.kind === 'npc' && want.includes(e.templateId)) {
          out[e.templateId] = { x: e.pos.x, z: e.pos.z };
        }
      }
      out.player = sim.player.pos;
      return out;
    });
    console.log(JSON.stringify(d, null, 1));
    break;
  }
  await b.disconnect();
})().catch(e => console.error('ERR', e.message));
