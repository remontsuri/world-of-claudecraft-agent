// browser_bridge.cjs — online WoC <-> Python agent bridge (HTTP), resilient.
//
// Connects to the live browser tab (CDP :9222), reads window.__game.sim as the
// observation, applies low-level actions via g.controller / sim.*, and serves a
// flat `info` dict (compatible with python/world_state.build_world_state) over
// HTTP so the existing Python Agent loop can drive the REAL online world.
//
// RESILIENCE: the game tab can reload / SPA-navigate / CDP can blip. We never
// crash on a failed page.evaluate — we log, attempt a reconnect, and return
// ok:false so the Python side can retry. process-level handlers keep the bridge
// alive across transient errors (no silent exit 1 after 20 min).
//
// Run:  node browser_bridge.cjs
// Then point python BrowserEnv at http://127.0.0.1:8791

const { connect } = require('puppeteer-core');
const http = require('http');

const CDP = 'http://127.0.0.1:9222';
const PORT = 8791;
const TICK_MS = 220;

let page = null;
let browser = null;

// ---- never crash on a transient error ----
process.on('uncaughtException', (e) => { console.error('[bridge] uncaught:', e.message); });
process.on('unhandledRejection', (e) => { console.error('[bridge] unhandledRejection:', e && e.message); });

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// ---- safe page.evaluate with auto-reconnect ----
async function safeEval(fn, ...args) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      if (!page) throw new Error('no page');
      try { await page.bringToFront(); } catch (_) {}
      return await page.evaluate(fn, ...args);
    } catch (e) {
      console.error('[bridge] eval error (attempt ' + attempt + '):', e.message);
      await reconnect();
    }
  }
  return null;
}

async function reconnect() {
  try {
    if (browser) { try { await browser.disconnect(); } catch (_) {} }
    browser = await connect({ browserURL: CDP });
    for (const p of await browser.pages()) {
      const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
      if (u.includes('worldofclaudecraft')) { page = p; break; }
    }
    if (!page) { console.error('[bridge] reconnect: no game tab'); return false; }
    await page.bringToFront();
    await page.waitForFunction(
      '!!window.__game && !!window.__game.sim && !!window.__game.sim.player',
      { timeout: 60000 }
    );
    const dbg = await page.evaluate(() => ({
      url: location.href,
      ents: window.__game.sim.entities.size,
      player: !!window.__game.sim.player,
    })).catch(() => null);
    console.log('[bridge] reconnected to game tab', JSON.stringify(dbg));
    return true;
  } catch (e) {
    console.error('[bridge] reconnect failed:', e.message);
    page = null;
    return false;
  }
}

// ---- action application (mirrors agent_browser.mjs / bridge_online glue) ----
async function applyAction(idx) {
  switch (idx) {
    case 0: { // farm: chase + attack nearest living mob until it dies
      const targetId = await safeEval(() => {
        const g = window.__game, sim = g.sim, p = sim.player;
        let best = null, bd = Infinity;
        for (const e of sim.entities.values()) {
          if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0) continue;
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          if (d <= 120 && d < bd) { bd = d; best = e; }
        }
        return best ? best.id : null;
      });
      if (targetId == null) { try { await safeEval(() => { try { window.__game.sim.tabTarget(); } catch (_) {} }); } catch (_) {} break; }
      // unified chase+attack loop: move toward mob if far, attack if in melee
      for (let t = 0; t < 80; t++) {
        const st = await safeEval((id) => {
          const g = window.__game, sim = g.sim, p = sim.player;
          const e = sim.entities.get(id);
          if (!e || e.dead || (e.hp ?? 0) <= 0) return { gone: true };
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          if (d > 7) {
            // chase: face + move
            const desired = Math.atan2(dx, dz);
            let off = desired - p.facing;
            off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
            if (Math.abs(off) > 0.2) {
              if (off > 0) g.controller.move({ turnLeft: true, forward: true });
              else g.controller.move({ turnRight: true, forward: true });
            } else {
              g.controller.move({ forward: true });
            }
            return { d, phase: 'chase' };
          }
          // in melee: attack
          try { sim.targetEntity(id); } catch (_) {}
          try { sim.startAutoAttack(); } catch (_) {}
          try { if (typeof sim.castAbilityOn === 'function') sim.castAbilityOn(id, 0); } catch (_) {}
          return { d, phase: 'attack' };
        }, targetId);
        if (st.gone) break;
        await sleep(TICK_MS);
      }
      break;
    }
    case 1: // loot
      await safeEval(() => { try { window.__game.sim.interact(); } catch (_) {} });
      break;
    case 2: // accept_quest
      await safeEval(() => { try { window.__game.sim.interact(); } catch (_) {} });
      break;
    case 3: // turn_in_quest
      await safeEval(() => { try { window.__game.sim.interact(); } catch (_) {} });
      break;
    case 4: // sell_junk
      await safeEval(() => {
        try { window.__game.sim.interact(); } catch (_) {}
        try { window.__game.sim.sellAllJunk && window.__game.sim.sellAllJunk(); } catch (_) {}
      });
      break;
    default: // gather/craft/heal/equip/buy/noop
      await safeEval(() => { try { window.__game.controller.stop(); } catch (_) {} });
  }
  await sleep(TICK_MS);
}

async function navigateToCoord(tx, tz, maxSteps) {
  for (let i = 0; i < maxSteps; i++) {
    const done = await safeEval((tx, tz) => {
      const g = window.__game, sim = g.sim, p = sim.player;
      const dx = tx - p.pos.x, dz = tz - p.pos.z;
      const dist = Math.hypot(dx, dz);
      if (dist < 5) return true;
      // Geometry (measured live, Test 1b/1c): player.facing=0 -> +Z;
      // turnLeft INCREASES facing, turnRight DECREASES it. So forward moves
      // along (sin(facing), cos(facing)) in (x,z), i.e. desired = atan2(dx, dz).
      const desired = Math.atan2(dx, dz);
      let off = desired - p.facing;
      off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
      if (Math.abs(off) > 0.2) {
        if (off > 0) g.controller.move({ turnLeft: true, forward: true });
        else g.controller.move({ turnRight: true, forward: true });
      } else {
        g.controller.move({ forward: true });
      }
      return false;
    }, tx, tz);
    if (done) return true;
    await sleep(TICK_MS);
  }
  return false;
}

async function exploreWalk(steps) {
  // Simple sustained walk: forward + occasional turn (mirrors the working
  // raw_move path). Ignoring nearby-target seeking because it made the agent
  // jitter in place; plain forward actually covers ground (verified: raw_move
  // moves ~13yd / 5 calls).
  for (let i = 0; i < steps; i++) {
    const turn = (i % 7 === 6); // turn every 7th step to cover new ground
    await safeEval((t) => {
      try { window.__game.controller.stop(); } catch (_) {}
      if (t) {
        try { window.__game.controller.move({ turnLeft: true, forward: true }); } catch (_) {}
      } else {
        try { window.__game.controller.move({ forward: true }); } catch (_) {}
      }
    }, turn);
    await sleep(TICK_MS);
  }
  return false;
}

async function snapshot() {
  // Always re-resolve the live game tab before reading — the SPA can navigate
  // and the cached `page` can go stale (window.__game undefined -> empty nearby).
  // reconnect() is cheap and only reassigns `page` if needed.
  try { if (!page || !(await safeEval(() => !!(window.__game && window.__game.sim && window.__game.sim.player)))) await reconnect(); } catch (_) {}
  // Ensure the game tab is focused — without this, page.evaluate can run in a
  // stale context where window.__game.sim entities lack questIds (observed:
  // direct eval with bringToFront sees full questIds, bridge without it sees []).
  try { if (page) await page.bringToFront(); } catch (_) {}
  const r = await safeEval(() => {
    const g = (window).__game, sim = g.sim, p = sim.player;
    console.error('[bridge-dbg] ents=' + (sim.entities ? sim.entities.size : 'NONE') + ' player=' + (!!p) + ' pos=' + (p && p.pos ? (p.pos.x+','+p.pos.z) : 'NONE'));
    const nearby = [];
    for (const e of sim.entities.values()) {
      if (!e.pos) continue;
      const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z;
      const dist = Math.hypot(dx, dz);
      if (dist > 70) continue;
      nearby.push({
        id: e.id, kind: e.kind, type: e.kind, name: e.name,
        x: e.pos.x, z: e.pos.z, hp: e.hp, maxHp: e.maxHp,
        hostile: !!e.hostile, dead: !!e.dead, lootable: !!e.lootable, looted: !!e.looted,
        dist,
        // quest offers live on the NPC entity in the live online tab (e.g.
        // Brother Aldric.questIds = ["q_bones", ...]). The policy's accept_quest
        // candidate depends on this field, so it MUST be forwarded here.
        // Previously omitted -> accept_quest never appeared as a candidate.
        questIds: e.questIds || e.questId || null,
      });
    }
    const qSrc = (g.online && g.online.quests) || sim.quests || null;
    let active = [], done = [];
    if (Array.isArray(qSrc)) {
      for (const q of qSrc) {
        if (q.status === 'active' || q.state === 'active') active.push(q);
        else if (q.status === 'complete' || q.state === 'complete') done.push(q);
      }
    } else if (qSrc && typeof qSrc === 'object') {
      active = qSrc.active || [];
      done = qSrc.done || [];
    }
    const inv = (p.inventory || sim.inventory || []);
    const doneArr = Array.isArray(done) ? done : [];
    const qd = (typeof (g.online && g.online.questsDone) === 'number') ? g.online.questsDone : doneArr.length;
    return {
      player: { hp: p.hp, maxHp: p.maxHp, level: p.level, dead: !!p.dead },
      player_pos: [p.pos.x, p.pos.z],
      nearby,
      inventory: inv.map((it) => ({ quality: it.quality ?? 0, name: it.name })),
      quests: { active, done: doneArr },
      kills: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || p.kills || 0,
      xp: g.online ? g.online.xp : (p.xp || 0),
      copper: sim.copper || 0,
      deaths: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.deaths) || p.deaths || 0,
      quests_done: qd,
      in_combat: !!p.inCombat,
    };
  });
  return r || {};
}

// ---- HTTP server ----
const server = http.createServer(async (req, res) => {
  if (req.method !== 'POST') { res.writeHead(405); res.end('use POST'); return; }
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', async () => {
    let resp = { ok: false };
    try {
      const cmd = JSON.parse(body || '{}');
      if (cmd.action === 'step') {
        await applyAction(cmd.idx || 0);
        resp = { ok: true, info: await snapshot() };
      } else if (cmd.action === 'navigate') {
        const arrived = await navigateToCoord(cmd.x, cmd.z, cmd.max_steps || 80);
        resp = { ok: true, arrived, info: await snapshot() };
      } else if (cmd.action === 'snapshot') {
        resp = { ok: true, info: await snapshot() };
      } else if (cmd.action === 'raw_move') {
        await safeEval((kind) => {
          try { window.__game.controller.stop(); } catch (_) {}
          if (kind === 'forward') window.__game.controller.move({ forward: true });
          else if (kind === 'back') window.__game.controller.move({ back: true });
          else if (kind === 'turnLeft') window.__game.controller.move({ turnLeft: true });
          else if (kind === 'turnRight') window.__game.controller.move({ turnRight: true });
        }, cmd.kind);
        await sleep(TICK_MS);
        resp = { ok: true, info: await snapshot() };
      } else if (cmd.action === 'respawn') {
        await safeEval(() => {
          try { window.__game.sim.releaseSpirit(); } catch (_) {}
          try { window.__game.sim.resurrectAtSpiritHealer(); } catch (_) {}
        });
        await sleep(TICK_MS);
        resp = { ok: true, info: await snapshot() };
      } else if (cmd.action === 'explore') {
        // sustained walk: head toward nearest mob/NPC (or just forward if none),
        // so the agent actually covers ground instead of 1-step jitter.
        const arrived = await exploreWalk(cmd.steps || 10);
        resp = { ok: true, arrived, info: await snapshot() };
      } else {
        resp = { ok: false, error: 'unknown action' };
      }
    } catch (e) {
      resp = { ok: false, error: e.message };
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(resp));
  });
});

async function main() {
  if (!await reconnect()) { console.error('[bridge] initial connect failed'); process.exit(1); }
  console.log('[bridge] online game tab ready; serving on :' + PORT);
  server.listen(PORT);
}

main().catch((e) => { console.error('FATAL', e.message); process.exit(1); });
