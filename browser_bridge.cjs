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
const fs = require('fs');

process.on('uncaughtException', (e) => {
  try { fs.writeFileSync('bridge_crash.txt', 'uncaughtException: ' + (e && e.stack || e) + '\n'); } catch (_) {}
});
process.on('unhandledRejection', (e) => {
  try { fs.writeFileSync('bridge_crash.txt', 'unhandledRejection: ' + (e && e.stack || e) + '\n'); } catch (_) {}
});
process.on('exit', (code) => {
  try { fs.writeFileSync('bridge_crash.txt', 'exit code=' + code + ' at ' + new Date().toISOString() + '\n'); } catch (_) {}
  try { if (BRIDGE_PID_PATH && fs.existsSync(BRIDGE_PID_PATH)) fs.unlinkSync(BRIDGE_PID_PATH); } catch (_) {}
});

// CRITICAL: on shutdown (SIGTERM/SIGINT) release ALL held inputs in the game so
// the character does NOT keep moving/spinning after the bridge dies. The game
// does not auto-clear controller state on client disconnect, so a dead bridge
// would leave the character running in circles -> looks like a bot -> ban risk.
// SIGTERM is what the supervisor sends; we stop the character, then exit.
// (SIGKILL cannot be trapped — but the supervisor uses SIGTERM, see exit code 1.)
async function releaseInputsAndExit(code) {
  try {
    if (!browser) browser = await connect({ browserURL: CDP });
    const pages = await browser.pages();
    for (const p of pages) {
      const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
      if (!u.includes('worldofclaudecraft')) continue;
      try { await p.evaluate(() => { try { window.__game.controller.stop(); } catch (_) {} }); } catch (_) {}
    }
  } catch (_) {}
  try { if (fs.existsSync(BRIDGE_PID_PATH)) fs.unlinkSync(BRIDGE_PID_PATH); } catch (_) {}
  process.exit(code);
}
process.on('SIGTERM', () => { releaseInputsAndExit(0); });
process.on('SIGINT', () => { releaseInputsAndExit(0); });

console.error('[bridge] starting on port', 8791);

const CDP = 'http://127.0.0.1:9222';
const PORT = 8791;

// Static Farshore NPC positions + quest -> turn-in NPC, sourced from
// src/sim/content/farshore.ts (FARSHORE_NPCS / FARSHORE_QUESTS). The live game
// does NOT expose sim.questDefs / sim.npcDefs (verified: all false at runtime),
// so we hardcode the zone's static layout here so the agent always knows where
// to walk to turn in a quest, even when the NPC is far away and not loaded into
// sim.entities. Keep in sync with farshore.ts if the zone layout changes.
const FARSHORE_NPC_POS = {
  warden_coalfast: { x: 305, z: 66 },
  bellkeeper_tam: { x: 252, z: 18 },
  quartermaster_edda: { x: 298, z: 74 },
  mender_saul: { x: 312, z: 78 },
  fisher_nell: { x: 296, z: 80 },
  riftwatch_ollun: { x: 372, z: 2 },
};
const FARSHORE_QUEST_TURNIN = {
  q_fs_bell_at_the_landing: 'warden_coalfast',
  q_fs_bram_come_home: 'fisher_nell',
  q_fs_hold_the_riftfields: 'warden_coalfast',
  q_fs_moss_and_mending: 'mender_saul',
  q_fs_song_before_the_break: 'riftwatch_ollun',
  q_fs_stalkers_off_the_light: 'riftwatch_ollun',
  q_fs_steel_for_the_redoubt: 'quartermaster_edda',
  q_fs_the_great_break: 'warden_coalfast',
  q_fs_the_three_bells: 'bellkeeper_tam',
};
const TICK_MS = 220;

const path = require('path');
const BRIDGE_PID_PATH = path.join(__dirname, 'bridge.pid');
// WorldMemory JSON written by python/memory.py WorldMemory.remember_giver(). It is
// the persistent source for "quest X -> turn-in NPC at (x,z)" — the agent learns
// the giver at accept time (the live game does NOT expose giverId in sim.questLog).
// FARSHORE_* static tables are only a fallback when this file is absent/empty.
function loadWorldMemory() {
  try {
    const p = path.join(__dirname, 'python', 'world_memory.json');
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch (_) {
    return null;
  }
}

let page = null;
let browser = null;

// ---- never crash on a transient error ----
process.on('uncaughtException', (e) => { console.error('[bridge] uncaught:', e.message); });
process.on('unhandledRejection', (e) => { console.error('[bridge] unhandledRejection:', e && e.message); });

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// Reject if `promise` does not settle within `ms`. A hanging page.evaluate
// (e.g. execution context destroyed during respawn/death SPA navigation)
// must NOT block the command queue forever.
function withTimeout(promise, ms, label) {
  let timer;
  const timeout = new Promise((_, reject) =>
    { timer = setTimeout(() => reject(new Error((label || 'op') + ' timed out after ' + ms + 'ms')), ms); });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

const EVAL_TIMEOUT_MS = 8000;
const CMD_TIMEOUT_MS = 90000;

// ---- safe page.evaluate with auto-reconnect ----
async function safeEval(fn, ...args) {
  let lastErr = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      if (!page) throw new Error('no page');
      try { await page.bringToFront(); } catch (_) {}
      return await withTimeout(page.evaluate(fn, ...args), EVAL_TIMEOUT_MS, 'eval');
    } catch (e) {
      lastErr = e;
      console.error('[bridge] eval error (attempt ' + attempt + '):', e && e.message);
      // The game tab may have SPA-reloaded (respawn / character switch), leaving
      // the cached `page` pointing at a destroyed execution context. Re-acquire a
      // FRESH page handle from the browser instead of reusing the stale one.
      try { page = await withTimeout(freshPage(), EVAL_TIMEOUT_MS, 'freshPage'); } catch (_) {}
      if (!page) { try { await withTimeout(reconnect(), EVAL_TIMEOUT_MS, 'reconnect'); } catch (_) {} }
    }
  }
  // Surface the failure instead of returning null silently, so the caller can
  // mark this command as failed rather than hang.
  throw lastErr || new Error('safeEval failed after retries');
}


// Execute a concrete game API call and preserve API-level errors. Transport/
// page failures still go through safeEval and become null; an actual Sim API
// rejection becomes a structured error instead of being swallowed by `catch {}`.
async function simCall(method, args = []) {
  const result = await safeEval((name, argv) => {
    const sim = window.__game && window.__game.sim;
    if (!sim) throw new Error('game sim unavailable');
    const fn = sim[name];
    if (typeof fn !== 'function') throw new Error(`sim.${name} is not available`);
    try {
      fn.apply(sim, argv || []);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: String(e && (e.message || e) || 'unknown Sim API error') };
    }
  }, method, args);
  if (!result) throw new Error(`sim.${method} failed: no browser result`);
  if (!result.ok) throw new Error(`sim.${method}: ${result.error}`);
  return result;
}

// Re-acquire the live game tab handle from the browser (never reuse a cached one
// that may point at a destroyed execution context after a reload/character swap).
// Picks the FIRST tab whose execution context actually has a live player — this
// avoids grabbing a stale/closed tab whose window.__game is empty or holds an old
// character. (A simple url match is not enough: after a character switch there can
// be two worldofclaudecraft tabs, one dead.)
async function freshPage() {
  if (!browser) browser = await connect({ browserURL: CDP });
  let pages;
  try {
    pages = await browser.pages();
  } catch (_) {
    // stale CDP connection (browser was restarted / tab reloaded) -> reconnect
    browser = null;
    browser = await connect({ browserURL: CDP });
    pages = await browser.pages();
  }
  for (const p of pages) {
    const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
    if (!u.includes('worldofclaudecraft')) continue;
    try {
      const live = await p.evaluate(() =>
        !!(window.__game && window.__game.sim && window.__game.sim.player &&
           typeof window.__game.sim.player.level === 'number'));
      if (live) return p;
    } catch (_) { /* context dead, try next */ }
  }
  return null;
}

async function reconnect() {
  try {
    if (!browser) {
      browser = await withTimeout(connect({ browserURL: CDP }), EVAL_TIMEOUT_MS, 'connect');
    }
    let pages = await withTimeout(browser.pages(), EVAL_TIMEOUT_MS, 'pages');
    let found = null;
    for (const p of pages) {
      const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
      if (u.includes('worldofclaudecraft')) { found = p; break; }
    }
    if (!found) {
      await sleep(1500);
      pages = await withTimeout(browser.pages(), EVAL_TIMEOUT_MS, 'pages');
      for (const p of pages) {
        const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
        if (u.includes('worldofclaudecraft')) { found = p; break; }
      }
    }
    if (!found) { console.error('[bridge] reconnect: no game tab'); return false; }
    page = found;
    await page.bringToFront().catch(() => {});
    // Do NOT block startup on a 60s waitForFunction. The game may still be
    // booting/respawning; poll readiness quickly (with timeout) and let main()
    // start serving immediately. A background loop re-runs reconnect() until
    // the game tab is live.
    const ready = await safeEval(() =>
      !!(window.__game && window.__game.sim && window.__game.sim.player));
    if (!ready) {
      console.error('[bridge] reconnect: game tab present but window.__game not ready yet');
      return false;
    }
    const dbg = await page.evaluate(() => ({
      url: location.href,
      ents: window.__game.sim.entities.size,
      player: !!window.__game.sim.player,
    })).catch(() => null);
    console.error('[bridge] reconnected to game tab', JSON.stringify(dbg));
    return true;
  } catch (e) {
    console.error('[bridge] reconnect failed:', e.message);
    page = null;
    return false;
  }
}

// Background readiness pump: keeps trying reconnect() until the game tab is
// live, so the bridge serves immediately and heals itself after a respawn /
// SPA navigation instead of being stuck "not ready".
let _readyPumpRunning = false;
async function readyPump() {
  if (_readyPumpRunning) return;
  _readyPumpRunning = true;
  while (true) {
    if (!page) {
      const ok = await reconnect().catch(() => false);
      if (!ok) { await sleep(3000); continue; }
    }
    // still alive? probe quickly; if it dies, retry
    const alive = await safeEval(() =>
      !!(window.__game && window.__game.sim && window.__game.sim.player)).catch(() => false);
    if (!alive) { page = null; await sleep(3000); continue; }
    await sleep(5000);
  }
}

// ---- action application (mirrors agent_browser.mjs / bridge_online glue) ----
async function applyAction(idx, cmd) {
  switch (idx) {
    case 0: { // farm: chase + attack nearest HOSTILE living mob until it dies
      // NOTE: the live game tags peaceful NPCs (e.g. Fisher Bram, a quest
      // villager) as kind:'mob' too, but marks them hostile:false. We must only
      // target hostile mobs, otherwise the agent attacks peaceful NPCs.
      const targetId = await safeEval(() => {
        const g = window.__game, sim = g.sim, p = sim.player;
        let best = null, bd = Infinity;
        for (const e of sim.entities.values()) {
          if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0) continue;
          if (e.hostile === false) continue;  // peaceful NPC (quest giver / villager)
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          if (d <= 120 && d < bd) { bd = d; best = e; }
        }
        return best ? best.id : null;
      });
      // NO tabTarget() fallback: if no hostile mob is in range, do nothing rather
      // than tapping the nearest peaceful NPC / object (would waste the action and
      // can hit quest NPCs). The agent simply gets an inconclusive farm and may
      // choose explore/return instead.
      if (targetId == null) break;
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
          // in melee: FACE the mob first (swing only lands within MELEE_ARC of
          // facing — auto_attack.ts gates on facingDiff>MELEE_ARC), then attack.
          // Keep re-facing every tick: the mob moves, so a one-time face at entry
          // drifts out of arc and updatePlayerAutoAttack silently drops autoAttack.
          const desired = Math.atan2(dx, dz);
          let off = desired - p.facing;
          off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
          if (Math.abs(off) > 0.2) {
            if (off > 0) g.controller.move({ turnLeft: true });
            else g.controller.move({ turnRight: true });
            return { d, phase: 'face' };
          }
          try { sim.targetEntity(id); } catch (_) {}
          try { sim.startAutoAttack(); } catch (_) {}
          return { d, phase: 'attack', dead: !!p.dead };
        }, targetId);
        if (st.gone || st.dead) {
          // stop autoattack + movement so a stale move command can't linger
          try { sim.stopAutoAttack(); } catch (_) {}
          try { g.controller.stop(); } catch (_) {}
          break;
        }
        await sleep(TICK_MS);
      }
      break;
    }
    case 1: // loot
      await safeEval(() => { try { window.__game.sim.interact(); } catch (_) {} });
      break;
    case 2: { // accept_quest: accept the specific quest offered by the nearby NPC
      // cmd.questId is passed by the agent's Policy (ctx['quest'] from the quest NPC).
      // Calling sim.acceptQuest(questId) is the real API; a bare interact() does NOT
      // accept a quest in this build (that's why accept_quest was always inconclusive).
      const qid = (cmd && cmd.questId) || null;
      // Capture the giver (NPC id + live position) so Python can persist it in
      // WorldMemory as the turn-in location. The live game does NOT return giverId
      // inside sim.questLog, so the agent must learn it HERE (it knows the NPC).
      const npcId = (cmd && cmd.npcId) || null;
      let giverPos = null;
      if (npcId) {
        giverPos = await safeEval((id) => {
          const sim = window.__game.sim;
          for (const e of sim.entities.values()) {
            if (String(e.id) === String(id) && e.pos) return { x: e.pos.x, z: e.pos.z };
          }
          return null;
        }, npcId).catch(() => null);
      }
      lastAccept = { questId: qid, giverId: npcId, giverPos };
      if (qid) {
        await simCall('acceptQuest', [String(qid)]);
      } else {
        // fallback: interact with the nearest quest NPC (legacy path)
        await safeEval(() => { try { window.__game.sim.interact(); } catch (_) {} });
      }
      break;
    }
    case 3: { // turn_in_quest: turn in the specific ready quest
      const qid = (cmd && (cmd.questId || cmd.quest_id)) || (cmd && cmd.quest && cmd.quest.id) || null;
      if (qid) {
        await simCall('turnInQuest', [String(qid)]);
      } else {
        await safeEval(() => { try { window.__game.sim.interact(); } catch (_) {} });
      }
      break;
    }
    case 4: { // sell_junk: only works next to a vendor NPC
      // The live game only allows selling when the player is in interact range
      // of a vendor. A bare interact()/sellAllJunk() with no vendor nearby is a
      // no-op (and was producing huge inconclusive spam in the start zone where
      // there is no vendor). Guard on a nearby vendor entity.
      const hasVendor = await safeEval(() => {
        const g = window.__game, sim = g.sim, p = sim.player;
        for (const e of sim.entities.values()) {
          const isVendor = e.vendor || e.vendorItems || e.isVendor;
          if (!isVendor) continue;
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z;
          if (Math.hypot(dx, dz) <= 12) return true;
        }
        return false;
      });
      if (hasVendor) {
        await simCall('interact', []);
        await simCall('sellAllJunk', []);
      }
      break;
    }
    case 5: { // gather: harvest the nearest harvestable node within range
      const nodeId = await safeEval(() => {
        const g = window.__game, sim = g.sim, p = sim.player;
        let best = null, bd = Infinity;
        for (const e of sim.entities.values()) {
          const isNode = (e.kind === 'gather_node' || e.nodeType || e.gatherTier !== undefined);
          if (!isNode || e.dead || e.depleted) continue;
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          if (d <= 60 && d < bd) { bd = d; best = e.id; }
        }
        return best ? best.id : null;
      });
      if (nodeId != null) {
        await safeEval((id) => { try { window.__game.sim.harvestNode(String(id)); } catch (_) {} }, nodeId);
      }
      break;
    }
    case 6: { // craft — NOT exposed in the live client (sim.craft undefined).
      // Honest no-op with a console warning so it is never mistaken for a
      // successful craft (no fake capability, no silent stop()).
      console.warn('[bridge] craft requested but sim.craft is not exposed in client -> unsupported');
      break;
    }
    case 7: { // heal: use the first health potion in the bag (if any)
      const used = await safeEval(() => {
        const sim = window.__game.sim;
        const inv = sim.inventory;
        const list = inv instanceof Map ? Array.from(inv.values()) : (Array.isArray(inv) ? inv : []);
        for (const slot of list) {
          if (!slot) continue;
          const def = slot.def || slot.itemDef || {};
          const name = (def.name || '').toLowerCase();
          const id = slot.itemId || def.id;
          if (!id) continue;
          // health potion / healing draught: client useItem handles the heal
          if (/potion|draught|tonic|elixir|heal/i.test(name)) {
            try { sim.useItem(id); return true; } catch (_) { return false; }
          }
        }
        return false;
      });
      // if no potion was available, this is an honest no-op (policy learns waste)
      if (!used) console.warn('[bridge] heal requested but no potion in bag -> no-op');
      break;
    }
    case 8: { // equip: equip the first unequipped gear item (if any)
      const equipped = await safeEval(() => {
        const sim = window.__game.sim;
        const inv = sim.inventory;
        const list = inv instanceof Map ? Array.from(inv.values()) : (Array.isArray(inv) ? inv : []);
        for (const slot of list) {
          if (!slot) continue;
          const def = slot.def || slot.itemDef || {};
          const id = slot.itemId || def.id;
          if (!id || !def.equipSlot) continue; // only real gear
          try { sim.equipItem(id); return true; } catch (_) { return false; }
        }
        return false;
      });
      if (!equipped) console.warn('[bridge] equip requested but nothing equippable -> no-op');
      break;
    }
    case 9: { // buy: buy a health potion from a nearby vendor (default minor_healing_potion)
      // Real API: sim.buyItem(npcId, itemId) (src/world_api/inventory.ts). If no
      // vendor is in range, honest no-op (policy learns waste).
      const DEFAULT_BUY = 'minor_healing_potion';
      const v = await safeEval((itemId) => {
        const sim = window.__game.sim, p = sim.player;
        for (const e of sim.entities.values()) {
          if ((e.kind === 'npc' || e.type === 'npc') && (e.vendor || e.isVendor || e.vendorItems)) {
            const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z;
            if (Math.hypot(dx, dz) <= 12) {
              try { sim.buyItem(e.id, itemId); return e.id; } catch (_) { return null; }
            }
          }
        }
        return null;
      }, DEFAULT_BUY);
      if (v == null) console.warn('[bridge] buy requested but no vendor in range -> no-op');
      break;
    }
    default: // noop / unknown
      await safeEval(() => { try { window.__game.controller.stop(); } catch (_) {} });
  }
  await sleep(TICK_MS);
}

async function navigateToCoord(tx, tz, maxSteps) {
  // IMPORTANT: controller.move({turnLeft:true, forward:true}) is a steering
  // action, not a rotation-in-place action. Using it every tick while chasing a
  // point makes the character orbit/spiral around the target. Navigation therefore
  // separates TURN and FORWARD into different ticks.
  let lastDist = Infinity;
  let stagnant = 0;
  let detour = 0;        // remaining ticks of a side-step detour
  let detourDir = 1;     // +1 = strafe/veer right, -1 = left
  // helper: re-read CURRENT distance after any move so the loop can see real progress
  const freshDist = (p) => Math.hypot(tx - p.pos.x, tz - p.pos.z);
  for (let i = 0; i < maxSteps; i++) {
    // Each eval issues the move AND waits one game tick, then returns the FRESH
    // distance (measured AFTER the move). Previously the distance was computed
    // BEFORE the move and returned unchanged, so the loop could never tell a
    // detour was making progress -> it stalled at the wall and gave up.
    const st = await safeEval(async (tx, tz, detour, detourDir) => {
      const g = window.__game, sim = g.sim, p = sim.player;
      const dx = tx - p.pos.x, dz = tz - p.pos.z;
      const dist = Math.hypot(dx, dz);
      if (dist < 5) {
        try { g.controller.stop(); } catch (_) {}
        return { done: true, dist, phase: 'arrived' };
      }
      const tick = () => new Promise((r) => setTimeout(r, 60));
      // While detouring around an obstacle, take a fixed side-step: turn toward
      // the detour direction and move forward. This walks AROUND walls instead
      // of grinding against them forever.
      if (detour > 0) {
        const desired = Math.atan2(dx, dz);
        let off = desired - p.facing;
        off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
        // bias heading: aim 60deg to the side of the goal so we circle the wall
        const side = off + detourDir * (Math.PI / 3);
        const abs = Math.abs(side);
        try { g.controller.stop(); } catch (_) {}
        if (abs > 0.35) {
          if (side > 0) g.controller.move({ turnLeft: true });
          else g.controller.move({ turnRight: true });
        } else {
          g.controller.move({ forward: true });
        }
        await tick();
        const p2 = sim.player;
        return { done: false, dist: Math.hypot(tx - p2.pos.x, tz - p2.pos.z), phase: 'detour', off };
      }
      const desired = Math.atan2(dx, dz);
      let off = desired - p.facing;
      off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
      const abs = Math.abs(off);

      // Large heading error: rotate in place. Direct controller.move() accepts
      // turnLeft/turnRight without forward, unlike the high-level applyAction path.
      if (abs > 0.35) {
        try { g.controller.stop(); } catch (_) {}
        if (off > 0) g.controller.move({ turnLeft: true });
        else g.controller.move({ turnRight: true });
        await tick();
        const p2 = sim.player;
        return { done: false, dist: Math.hypot(tx - p2.pos.x, tz - p2.pos.z), phase: 'turn', off };
      }

      // Once aligned, take a short straight step. Recompute heading every tick.
      try { g.controller.stop(); } catch (_) {}
      g.controller.move({ forward: true });
      await tick();
      const p2 = sim.player;
      return { done: false, dist: Math.hypot(tx - p2.pos.x, tz - p2.pos.z), phase: 'forward', off };
    }, tx, tz, detour, detourDir);

    if (!st) throw new Error('navigation evaluate failed');
    if (st.done) return true;

    // If distance is not improving for too long, we are blocked by a wall.
    // Start a detour (side-step) instead of giving up, so the agent walks
    // AROUND the obstacle rather than grinding against it forever.
    if (st.dist >= lastDist - 0.25) stagnant += 1;
    else stagnant = 0;
    lastDist = st.dist;
    if (stagnant >= 6 && detour === 0) {
      // begin a detour burst: veer to whichever side, for ~14 ticks
      detour = 14;
      stagnant = 0;
      // alternate detour direction each time so we don't loop one way
      detourDir = -detourDir;
    } else if (detour > 0) {
      detour -= 1;
      if (detour === 0) stagnant = 0; // re-evaluate straight path after detour
    }
    if (stagnant >= 30) break; // genuine unreachable (or far) — give up cleanly
    await sleep(TICK_MS);
  }
  await safeEval(() => { try { window.__game.controller.stop(); } catch (_) {} });
  return false;
}

async function exploreWalk(steps) {
  // Exploration must not contain a fixed "turn every N ticks" rule: that creates
  // a literal circle and prevents discovering distant NPCs. Walk straight for the
  // bounded burst; the learned policy can choose another explore burst later.
  for (let i = 0; i < steps; i++) {
    await safeEval(() => {
      try { window.__game.controller.stop(); } catch (_) {}
      window.__game.controller.move({ forward: true });
    });
    await sleep(TICK_MS);
  }
  await safeEval(() => { try { window.__game.controller.stop(); } catch (_) {} });
  return false;
}

async function findSpiritHealer() {
  // The server checks proximity to a spirit healer; calling
  // resurrectAtSpiritHealer() immediately after releaseSpirit() is therefore
  // guaranteed to fail when the corpse is elsewhere. Search the full entity
  // collection (not just nearby) for a healer and return its world position.
  const r = await safeEval(() => {
    const sim = window.__game && window.__game.sim;
    if (!sim) return null;
    const values = [];
    try { for (const e of sim.entities.values()) values.push(e); } catch (_) {}
    const npcDefs = sim.npcDefs || null;
    if (npcDefs) {
      try {
        if (typeof npcDefs.forEach === 'function') npcDefs.forEach((e) => values.push(e));
        else for (const k of Object.keys(npcDefs)) values.push(npcDefs[k]);
      } catch (_) {}
    }
    const score = (e) => {
      if (!e) return -1;
      const text = [
        e.name, e.title, e.role, e.type, e.kind, e.npcType, e.subtype
      ].filter(Boolean).join(' ').toLowerCase();
      let s = 0;
      if (e.isSpiritHealer || e.spiritHealer || e.isHealer) s += 100;
      if (text.includes('spirit healer')) s += 100;
      else if (text.includes('spirit-healer')) s += 100;
      else if (text.includes('healer')) s += 40;
      return s;
    };
    let best = null, bestScore = 0;
    for (const e of values) {
      const p = e && e.pos;
      const sc = score(e);
      if (p && Number.isFinite(p.x) && Number.isFinite(p.z) && sc > bestScore) {
        best = { id: e.id, name: e.name || e.title || '', x: p.x, z: p.z, score: sc };
        bestScore = sc;
      }
    }
    return best;
  });
  return r;
}

async function snapshot() {
  // UNCONDITIONAL fresh page handle. The SPA can navigate / the character can
  // switch, which destroys the cached execution context and leaves a STALE
  // `window.__game` (wrong/old character). Re-resolving the live tab every call
  // is the only correct fix — checking "player empty or not" would miss the case
  // where the stale page shows a DIFFERENT valid-looking character. browser.pages()
  // is a cheap CDP target-list call (ms), not a hot-path bottleneck at 4Hz.
  const cur = await freshPage();
  if (!cur) return { ok: false, error: 'no game tab', _dbg: { freshFound: false } };
  let curUrl = '?';
  try { curUrl = (typeof cur.url === 'function') ? cur.url() : (cur.url || '?'); } catch (_) {}
  try { await cur.bringToFront(); } catch (_) {}
  async function ev(fn, ...a) {
    // single handle for the whole snapshot call -> no cross-evaluate desync
    try { return await cur.evaluate(fn, ...a); } catch (e) {
      console.error('[bridge] snapshot eval error:', e.message);
      return null;
    }
  }
  const alive = await ev(() => !!(window.__game && window.__game.sim && window.__game.sim.player));
  if (!alive) {
    const hasGame = await ev(() => (typeof window.__game));
    return { ok: false, error: 'game not ready', _dbg: { freshFound: true, curUrl, alive: false, typeofGame: hasGame } };
  }
  const r = await ev(() => {
    const g = (window).__game, sim = g.sim, p = sim.player;
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
    // Real active quests live in sim.questLog (Map<questId, QuestProgress>),
    // NOT sim.quests / g.online.quests (those are empty in this build). QuestProgress
    // = { questId, counts:number[], state:'active'|'ready'|'done' }. Objectives'
    // required counts come from the QuestDef (sim.questDefs / world.questDefs).
    let active = [], ready = [], done = [];
    const qlog = sim.questLog || (g.world && g.world.questLog) || null;
    const qdefs = sim.questDefs || (g.world && g.world.questDefs) || null;
    // Build a questId -> turn-in NPC id map, then resolve NPC positions from
    // EVERY available source (live entities + static npcDefs), so the agent knows
    // where to walk even when the NPC is far away and not loaded into entities.
    const npcPos = {};
    const mergeNpc = (id, x, z) => {
      if (id && x != null && z != null && !npcPos[id]) npcPos[id] = { x, z };
    };
    for (const e of sim.entities.values()) {
      if (e.pos) mergeNpc(e.id, e.pos.x, e.pos.z);
    }
    const npcDefs = sim.npcDefs || (g.world && g.world.npcDefs) || null;
    if (npcDefs) {
      const addFrom = (m) => {
        if (!m) return;
        if (typeof m.forEach === 'function') m.forEach((d, id) => { if (d && d.pos) mergeNpc(id, d.pos.x, d.pos.z); });
        else for (const id in m) { const d = m[id]; if (d && d.pos) mergeNpc(id, d.pos.x, d.pos.z); }
      };
      addFrom(npcDefs);
    }
    if (qlog && typeof qlog.forEach === 'function') {
      qlog.forEach((qp, qid) => {
        const st = qp.state || 'active';
        const def = (qdefs && (qdefs.get ? qdefs.get(qid) : qdefs[qid])) || null;
        const objs = (def && Array.isArray(def.objectives))
          ? def.objectives.map((o, i) => ({
              current: (qp.counts && qp.counts[i]) || 0,
              required: (o && (o.count != null ? o.count : o.required)) || 0,
            }))
          : (qp.counts || []).map((c) => ({ current: c, required: c }));
        // turn-in location is resolved on the NODE side after evaluate returns
        // (FARSHORE_* constants live in Node scope, not in the browser context
        // where this fn runs -> referencing them here throws ReferenceError).
        const entry = { id: qid, state: st, objectives: objs, turnInNpc: null };
        if (st === 'active') active.push(entry);
        else if (st === 'ready') ready.push(entry);
        else if (st === 'done') done.push(entry);
      });
    } else {
      // legacy fallback (should not happen in this build)
      const qSrc = (g.online && g.online.quests) || sim.quests || null;
      if (Array.isArray(qSrc)) {
        for (const q of qSrc) {
          if (q.status === 'active' || q.state === 'active') active.push(q);
          else if (q.status === 'complete' || q.state === 'complete') done.push(q);
        }
      } else if (qSrc && typeof qSrc === 'object') {
        active = qSrc.active || [];
        done = qSrc.done || [];
      }
    }
    const inv = (p.inventory || sim.inventory || []);
    const doneArr = Array.isArray(done) ? done : [];
    const qd = (typeof (g.online && g.online.questsDone) === 'number') ? g.online.questsDone : doneArr.length;
    return {
      player: { hp: p.hp, maxHp: p.maxHp, level: p.level, dead: !!p.dead },
      player_pos: [p.pos.x, p.pos.z],
      nearby,
      inventory: inv.map((it) => ({ quality: it.quality ?? 0, name: it.name })),
      quests: { active, ready, done: doneArr },
      kills: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || p.kills || 0,
      xp: g.online ? g.online.xp : (p.xp || 0),
      copper: sim.copper || 0,
      deaths: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.deaths) || p.deaths || 0,
      quests_done: qd,
      in_combat: !!p.inCombat,
    };
  });
  // Resolve quest turn-in NPC position on the NODE side. Priority:
  //   1. live entity pos (already in q.turnInNpc, skipped above)
  //   2. WorldMemory JSON (python/world_memory.json) — agent persists giver here
  //      at accept time; this is the real persistent source for "quest X -> NPC".
  //   3. FARSHORE_* static tables — fallback only (first run / unknown zone).
  const wm = loadWorldMemory();
  if (r && r.quests) {
    for (const bucket of ['active', 'ready', 'done']) {
      for (const q of (r.quests[bucket] || [])) {
        if (q.turnInNpc) continue;
        let pos = null;
        // 2. WorldMemory (agent-acquired, persists across runs)
        const wg = wm && wm.quest_givers && wm.quest_givers[q.id];
        if (wg && wg.giver_pos) pos = { x: wg.giver_pos.x, z: wg.giver_pos.z };
        // 3. FARSHORE static fallback
        if (!pos) {
          const turnInId = FARSHORE_QUEST_TURNIN[q.id] || null;
          if (turnInId && FARSHORE_NPC_POS[turnInId]) {
            pos = { x: FARSHORE_NPC_POS[turnInId].x, z: FARSHORE_NPC_POS[turnInId].z };
          }
        }
        if (pos) q.turnInNpc = pos;
      }
    }
  }
  return { ok: true, info: r || {}, _dbg: { rIsNull: r === null, rType: typeof r, playerKeys: r && r.player ? Object.keys(r.player) : null, nearbyLen: r && r.nearby ? r.nearby.length : null } };
}

// Return ONLY the inner info object from snapshot() (no {ok,info,_dbg} wrapper),
// so command handlers can do `info: await snapshotInfo()` and the Python client
// receives the flat world state (player/nearby/quests) directly in resp.info.
async function snapshotInfo() {
  const s = await snapshot();
  return (s && s.info) || {};
}

// ---- HTTP server ----
// Command serialization: all mutations to the single live game tab run through
// ONE promise chain. A farm() holds the tab for ~17s; without this, a concurrent
// raw_move/respawn from another caller would interleave and corrupt the world.
let cmdQueue = Promise.resolve();
// Last accept_quest result (questId/giverId/giverPos), surfaced to Python so it
// can persist the turn-in NPC in WorldMemory (the game does not return giverId).
let lastAccept = null;
const server = http.createServer(async (req, res) => {
  // Health probe (start_ragent.bat does `HEAD /` expecting 200). Keep POST
  // for real commands; answer liveness with 200 so the launcher starts the agent.
  if (req.method === 'GET' || req.method === 'HEAD') {
    const url = (req.url || '/').split('?')[0];
    if (url === '/health') {
      // Honest health: prove the bridge is actually driving a LIVE game tab,
      // not just that the HTTP socket is open. Used by start_ragent.bat so it
      // only starts the Python agent once the game is really reachable.
      const health = { ok: true, bridge: true, page: false, game: false };
      if (page) {
        health.page = true;
        try {
          health.game = !!(await page.evaluate(
            () => !!(window.__game && window.__game.sim && window.__game.sim.player)));
        } catch (_) { health.game = false; }
      }
      res.writeHead(200, { 'content-type': 'application/json', 'Content-Length': Buffer.byteLength(JSON.stringify(health)), 'Connection': 'close' });
      res.end(JSON.stringify(health));
      return;
    }
    // simple liveness probe (back-compat)
    res.writeHead(200, { 'content-type': 'application/json', 'Content-Length': Buffer.byteLength(JSON.stringify({ ok: true, alive: true })), 'Connection': 'close' });
    res.end(JSON.stringify({ ok: true, alive: true }));
    return;
  }
  if (req.method !== 'POST') { res.writeHead(405); res.end('use POST'); return; }
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    const work = (async () => {
      let resp = { ok: false };
      try {
        const cmd = JSON.parse(body || '{}');
      if (cmd.action === 'snapshot') {
        // Agent primes its first observation with POST {action:'snapshot'}
        // (browser_env.py __init__). Return the live game snapshot.
        resp = { ok: true, info: await snapshotInfo() };
      } else if (cmd.action === 'step') {
        await applyAction(cmd.idx || 0, cmd);
        resp = { ok: true, info: await snapshotInfo() };
        // Surface the giver the agent just accepted from (if this step was accept_quest)
        if (lastAccept && (cmd.idx === 2 || cmd.questId)) {
          resp.giver = lastAccept;
          lastAccept = null;
        }
      } else if (cmd.action === 'navigate') {
        const arrived = await navigateToCoord(cmd.x, cmd.z, cmd.max_steps || 80);
        resp = { ok: true, arrived, info: await snapshotInfo() };
      } else if (cmd.action === 'raw_move') {
        await safeEval((kind) => {
          try { window.__game.controller.stop(); } catch (_) {}
          if (kind === 'forward') window.__game.controller.move({ forward: true });
          else if (kind === 'back') window.__game.controller.move({ back: true });
          else if (kind === 'turnLeft') window.__game.controller.move({ turnLeft: true });
          else if (kind === 'turnRight') window.__game.controller.move({ turnRight: true });
        }, cmd.kind);
        await sleep(TICK_MS);
        resp = { ok: true, info: await snapshotInfo() };
      } else if (cmd.action === 'respawn') {
        // Death is a two-stage server operation:
        //   1) release the spirit;
        //   2) WALK THE GHOST to the spirit healer;
        //   3) resurrect at the healer.
        // Calling resurrectAtSpiritHealer() at the corpse is rejected by the
        // authoritative server. The old bridge did exactly that, so every death
        // became a permanent ghost.
        const released = await safeEval(() => {
          const sim = window.__game.sim;
          if (!sim.player || !sim.player.dead) return { dead: false };
          sim.releaseSpirit();
          return { dead: !!sim.player.dead };
        });
        if (!released) throw new Error('respawn failed: releaseSpirit evaluate failed');

        // Give the server a tick to switch the character into ghost state.
        await sleep(TICK_MS);
        // The authoritative server requires the ghost to be near the Spirit
        // Healer. Find a real healer and walk there as the ghost, then resurrect.
        const healer = await findSpiritHealer();
        if (!healer) throw new Error('respawn failed: spirit healer not found');
        console.error('[bridge] spirit healer target', JSON.stringify(healer));
        const arrived = await navigateToCoord(healer.x, healer.z, 160);
        if (!arrived) throw new Error('respawn failed: could not reach spirit healer');
        await simCall('resurrectAtSpiritHealer', []);
        let revived = false;
        for (let i = 0; i < 50 && !revived; i++) {
          await sleep(TICK_MS);
          const probe = await safeEval(() => ({
            dead: !!(window.__game.sim.player && window.__game.sim.player.dead),
            hp: window.__game.sim.player && window.__game.sim.player.hp
          }));
          revived = !!(probe && !probe.dead);
        }
        if (!revived) {
          throw new Error('respawn failed: spirit healer did not revive player');
        }
        resp = { ok: true, info: await snapshotInfo(), healer };
      } else if (cmd.action === 'explore') {
        // sustained walk: head toward nearest mob/NPC (or just forward if none),
        // so the agent actually covers ground instead of 1-step jitter.
        const arrived = await exploreWalk(cmd.steps || 10);
        resp = { ok: true, arrived, info: await snapshotInfo() };
      } else if (cmd.action === 'accept_quest') {
        // Agent requests a specific quest (by id) — call the real sim API.
        // The game server validates proximity to the giver; we just forward it.
        // Accept BOTH wire keys: Python wow_env sends `quest_id`, older/other
        // callers send `questId`. Mismatch here silently dropped the id and
        // made accept_quest inconclusive / turn_in_quest fail with "requires questId".
        const qid = cmd.questId || cmd.quest_id || (cmd.quest && cmd.quest.id);
        if (!qid) { resp = { ok: false, error: 'accept_quest requires questId' }; }
        else {
          const r = await simCall('acceptQuest', [String(qid)]);
          resp = { ok: true, api: r, info: await snapshotInfo() };
        }
      } else if (cmd.action === 'turn_in_quest') {
        // Turn in a completed quest by id — call the real sim API.
        // Accept BOTH wire keys (see accept_quest note): Python wow_env sends `quest_id`.
        const qid = cmd.questId || cmd.quest_id || (cmd.quest && cmd.quest.id);
        if (!qid) { resp = { ok: false, error: 'turn_in_quest requires questId' }; }
        else {
          const r = await simCall('turnInQuest', [String(qid)]);
          resp = { ok: true, api: r, info: await snapshotInfo() };
        }
      } else {
        resp = { ok: false, error: 'unknown action' };
      }
    } catch (e) {
      resp = { ok: false, error: e.message };
    }
    return resp;   // DO NOT write the HTTP response here — the response is sent
                   // by the cmdQueue chain below, so a cmdTimeout can answer the
                   // client instead of leaving the socket hanging ("no HTTP headers").
  });
  // Run `work` on the sequential command queue, but NEVER let a single command
  // block the queue forever. If it exceeds CMD_TIMEOUT_MS (e.g. a page.evaluate
  // hung during a respawn/SPA navigation), answer with a timeout error AND reset
  // the queue so subsequent commands still run.
  //
  // The HTTP response is written HERE (not inside work()) so whichever settles
  // first — the real result or the timeout — actually answers the client. The
  // orphaned work() may still finish later; guard the write so it cannot touch
  // an already-closed response.
  cmdQueue = cmdQueue.then(() =>
    withTimeout(work(), CMD_TIMEOUT_MS, 'cmd')
      .then((r) => ({ ok: r && r.ok !== undefined ? r.ok : false, ...(r || {}), _timedOut: false }))
      .catch((err) => ({ ok: false, error: (err && err.message) || 'cmd failed', _timedOut: true }))
      .finally(() => { cmdQueue = Promise.resolve(); })
  ).then((resp) => {
    if (!res.writableEnded) {
      const body = JSON.stringify(resp);
      res.writeHead(200, { 'content-type': 'application/json', 'Content-Length': Buffer.byteLength(body), 'Connection': 'close' });
      res.end(body);
    }
  });
  });
});

async function main() {
  try { fs.writeFileSync(BRIDGE_PID_PATH, String(process.pid), 'utf8'); } catch (_) {}
  server.on('error', (e) => {
    console.error('[bridge] server error:', e.code || e.message);
    process.exit(e.code === 'EADDRINUSE' ? 2 : 1);
  });
  // Serve IMMEDIATELY. Do not block startup on reconnect(): the game tab may be
  // booting/respawning. The readiness pump heals the connection in the background.
  server.listen(PORT, () => {
    console.log('[bridge] serving on :' + PORT + ' (game tab may still be connecting)');
  });
  readyPump();
}

main().catch((e) => { console.error('FATAL', e.message); process.exit(1); });
