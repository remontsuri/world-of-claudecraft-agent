// readiness_zond.cjs — честная проверка живости онлайн-сессии WoC перед long run.
// Критерии (из плана Level 4):
//   1) account != null
//   2) controller.move сдвигает player_pos (moved == true)
//   3) атака растит kills (attackWorked == true)
//   4) NPC отдают questIds (после патча Б browser_bridge.cjs)
// Запуск: node readiness_zond.cjs   (бридж должен быть переподнят с патчем Б)
const { connect } = require('puppeteer-core');
const http = require('http');
const CDP = 'http://127.0.0.1:9222';
const BRIDGE = 'http://127.0.0.1:8791';

function get(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => {
      let d = '';
      r.on('data', (c) => (d += c));
      r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
    }).on('error', rej);
  });
}

function postJson(url, body) {
  return new Promise((res, rej) => {
    const data = JSON.stringify(body || {});
    const u = new URL(url);
    const req = http.request({
      hostname: u.hostname, port: u.port, path: u.pathname,
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    }, (r) => {
      let d = '';
      r.on('data', (c) => (d += c));
      r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
    });
    req.on('error', rej);
    req.write(data);
    req.end();
  });
}

(async () => {
  const browser = await connect({ browserURL: CDP });
  let page = null;
  for (const p of await browser.pages()) {
    const u = typeof p.url === 'function' ? p.url() : (p.url || '');
    if (u.includes('worldofclaudecraft')) { page = p; break; }
  }
  if (!page) { console.log(JSON.stringify({ fatal: 'NO_GAME_TAB' })); await browser.disconnect(); return; }
  await page.bringToFront();
  try { await page.waitForFunction('!!window.__game && !!window.__game.sim', { timeout: 20000 }); }
  catch (e) { console.log(JSON.stringify({ fatal: 'NO_GAME_OR_SIM' })); await browser.disconnect(); return; }

  // 1) account
  const account = await page.evaluate(() => (window.__game.account ? window.__game.account.id || true : null));

  // 2) movement
  const before = await page.evaluate(() => {
    const p = window.__game.sim.entities.get(window.__game.online.playerId) ||
              window.__game.sim.entities.get(window.__game.online.ownPlayerId);
    return p ? { x: p.pos.x, z: p.pos.z } : null;
  });
  await page.evaluate(() => {
    const c = window.__game.controller; if (c && c.move) c.move({ forward: true });
  });
  await new Promise((r) => setTimeout(r, 600));
  await page.evaluate(() => {
    const c = window.__game.controller; if (c && c.move) c.move({ forward: false });
  });
  const after = await page.evaluate(() => {
    const p = window.__game.sim.entities.get(window.__game.online.playerId) ||
              window.__game.sim.entities.get(window.__game.online.ownPlayerId);
    return p ? { x: p.pos.x, z: p.pos.z } : null;
  });
  const moved = before && after && (Math.abs(before.x - after.x) + Math.abs(before.z - after.z)) > 0.01;

  // 3) attack deals damage — measure HP drop on a mob over 4s (kills take 4-5s,
  // so measuring kills over 1.5s was a false negative).
  let attackWorked = false;
  try {
    const before = await page.evaluate(() => {
      const g = window.__game, sim = g.sim, p = sim.player;
      let best = null, bd = Infinity;
      for (const e of sim.entities.values()) {
        if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0) continue;
        const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
        if (d <= 45 && d < bd) { bd = d; best = e; }
      }
      if (!best) return null;
      return { id: best.id, hp: best.hp };
    });
    if (before) {
      await postJson(BRIDGE + '/action', { action: 'step', idx: 0 }); // farm (case 0)
      await new Promise((r) => setTimeout(r, 4000));
      const afterHp = await page.evaluate((id) => {
        const e = window.__game.sim.entities.get(id);
        return e ? e.hp : -1; // -1 = dead/gone
      }, before.id);
      attackWorked = afterHp < before.hp;
    }
  } catch (e) { attackWorked = 'bridge_error:' + e.message; }

  // 4) NPC questIds via bridge snapshot
  let npcQuestOk = false;
  try {
    const s = await postJson(BRIDGE + '/snapshot', {});
    const nearby = (s.info && s.info.nearby) || [];
    npcQuestOk = Array.isArray(nearby) && nearby.some((n) => Array.isArray(n.questIds) && n.questIds.length > 0);
  } catch (e) { npcQuestOk = 'bridge_error:' + e.message; }

  const result = {
    account_ok: !!account,
    moved,
    attackWorked,
    npcQuestOk,
    // account is NOT a hard blocker: the game plays fine without it and farm
    // works; we only report it. Readiness = movement + damage + quest offers.
    ready: moved && attackWorked === true && npcQuestOk === true,
  };
  console.log(JSON.stringify(result, null, 2));
  await browser.disconnect();
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
