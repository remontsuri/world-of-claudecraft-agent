// throwaway: hook ctx.error to capture WHY turnInQuest refuses, then call it
const { connect } = require('puppeteer-core');
(async () => {
  const b = await connect({ browserURL: 'http://127.0.0.1:9222' });
  const pages = await b.pages();
  for (const p of pages) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (!u.includes('worldofclaudecraft')) continue;
    const d = await p.evaluate(() => {
      return new Promise((resolve) => {
        const g = window.__game, sim = g.sim;
        // walk to wilkes first
        let ticks = 0;
        const iv = setInterval(() => {
          ticks++;
          let wilkes = null;
          for (const e of sim.entities.values()) if (e.templateId === 'trader_wilkes') wilkes = e;
          if (!wilkes) { clearInterval(iv); resolve({ err: 'no wilkes' }); return; }
          const ppos = sim.player.pos;
          const d2 = Math.hypot(wilkes.pos.x - ppos.x, wilkes.pos.z - ppos.z);
          if (d2 <= 5 || ticks > 60) {
            clearInterval(iv);
            try { g.controller.stop(); } catch (_) {}
            // capture errors: monkey-patch the chat/log? Instead read lastCraftResult-like surface.
            // Simplest: check distance + state, then call.
            let caught = null;
            try {
              const origErr = console.error;
              console.error = (...a) => { caught = a.join(' '); origErr(...a); };
              sim.turnInQuest('q_boars');
              console.error = origErr;
            } catch (e) { caught = 'EXC ' + e.message; }
            setTimeout(() => {
              resolve({
                distAtTry: d2,
                caught,
                stateAfter: (sim.questLog.get('q_boars') || {}).state,
                playerPos: { x: sim.player.pos.x, z: sim.player.pos.z },
                wilkesPos: wilkes ? { x: wilkes.pos.x, z: wilkes.pos.z } : null,
              });
            }, 500);
            return;
          }
          const dx = wilkes.pos.x - ppos.x, dz = wilkes.pos.z - ppos.z;
          const desired = Math.atan2(dx, dz);
          let off = desired - ppos.facing;
          off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
          if (Math.abs(off) > 0.2) { if (off > 0) g.controller.move({ turnLeft: true, forward: true }); else g.controller.move({ turnRight: true, forward: true }); }
          else g.controller.move({ forward: true });
        }, 220);
      });
    });
    console.log(JSON.stringify(d, null, 1));
    break;
  }
  await b.disconnect();
})().catch(e => console.error('ERR', e.message));
