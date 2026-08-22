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

// ---- safe page.evaluate with auto-reconnect ----
async function safeEval(fn, ...args) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      if (!page) throw new Error('no page');
      try { await page.bringToFront(); } catch (_) {}
      return await page.evaluate(fn, ...args);
    } catch (e) {
      console.error('[bridge] eval error (attempt ' + attempt + '):', e.message);
      // The game tab may have SPA-reloaded (respawn / character switch), leaving
      // the cached `page` pointing at a destroyed execution context. Re-acquire a
      // FRESH page handle from the browser instead of reusing the stale one.
      try { page = await freshPage(); } catch (_) {}
      if (!page) { try { await reconnect(); } catch (_) {} }
    }
  }
  return null;
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
    // Reuse the existing browser connection; only (re)connect if we have none.
    // Forcing browser.disconnect() on every call breaks re-acquisition when the
    // game tab reloads (SPA navigation / respawn): connect() throws "already
    // connected", reconnect returns false, and the bridge stays on a stale page
    // forever -> empty snapshots. We only (re)connect when browser is null.
    if (!browser) {
      browser = await connect({ browserURL: CDP });
    }
    let pages = await browser.pages();
    let found = null;
    for (const p of pages) {
      const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
      if (u.includes('worldofclaudecraft')) { found = p; break; }
    }
    // If no page matched, the tab may have reloaded under a different handle;
    // retry once after a short wait.
    if (!found) {
      await sleep(1500);
      pages = await browser.pages();
      for (const p of pages) {
        const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
        if (u.includes('worldofclaudecraft')) { found = p; break; }
      }
    }
    if (!found) { console.error('[bridge] reconnect: no game tab'); return false; }
    page = found;
    await page.bringToFront().catch(() => {});
    await page.waitForFunction(
      '!!window.__game && !!window.__game.sim && !!window.__game.sim.player',
      { timeout: 60000 }
    );
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
        await safeEval((id) => { try { window.__game.sim.acceptQuest(String(id)); } catch (_) {} }, qid);
      } else {
        // fallback: interact with the nearest quest NPC (legacy path)
        await safeEval(() => { try { window.__game.sim.interact(); } catch (_) {} });
      }
      break;
    }
    case 3: { // turn_in_quest: turn in the specific ready quest
      const qid = (cmd && cmd.questId) || null;
      if (qid) {
        await safeEval((id) => { try { window.__game.sim.turnInQuest(String(id)); } catch (_) {} }, qid);
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
        await safeEval(() => {
          try { window.__game.sim.interact(); } catch (_) {}
          try { window.__game.sim.sellAllJunk && window.__game.sim.sellAllJunk(); } catch (_) {}
        });
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
  for (let i = 0; i < maxSteps; i++) {
    const done = await safeEval((tx, tz) => {
      const g = window.__game, sim = g.sim, p = sim.player;
      const dx = tx - p.pos.x, dz = tz - p.pos.z;
      const dist = Math.hypot(dx, dz);
      if (dist < 5) { try { g.controller.stop(); } catch (_) {} return true; }
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
  // always stop movement when navigation ends (target reached OR timeout)
  await safeEval(() => { try { window.__game.controller.stop(); } catch (_) {} });
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
  // UNCONDITIONAL fresh page handle. The SPA can navigate / the character can
  // switch, which destroys the cached execution context and leaves a STALE
  // `window.__game` (wrong/old character). Re-resolving the live tab every call
  // is the only correct fix — checking "player empty or not" would miss the case
  // where the stale page shows a DIFFERENT valid-looking character. browser.pages()
  // is a cheap CDP target-list call (ms), not a hot-path bottleneck at 4Hz.
  const cur = await freshPage();
  if (!cur) {
    console.error('[bridge] snapshot: no game tab (freshFound=false)');
    return { __error: 'no game tab' };
  }
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
    console.error('[bridge] snapshot: game not ready', JSON.stringify({ curUrl, alive: false, typeofGame: hasGame }));
    return { __error: 'game not ready' };
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
  // Return the FLAT snapshot object `r` (with player/nearby/quests/...), or an
  // {__error: msg} marker when the game tab is missing / not ready / evaluate
  // returned null. The server wraps this via snap() and propagates ok:false so
  // Python's BrowserEnv sees a real failure (not a live-alive empty character).
  // Previously returning {} here made a broken page look alive -> recovery never fired.
  if (r === null) {
    console.error('[bridge] snapshot: evaluate returned null (stale page context?)');
    return { __error: 'snapshot evaluate returned null' };
  }
  return r || {};
}

// Server-side wrapper: snapshot() returns either a flat info object `r` or an
// {__error: msg} marker. This turns a broken/missing game tab into a real
// {ok:false, error} so Python's BrowserEnv raises BrowserBridgeError (infra
// path) instead of treating an empty info as a live, alive character.
async function snap() {
  const r = await snapshot();
  if (r && r.__error) return { ok: false, error: r.__error };
  return { ok: true, info: r || {} };
}

// ---- HTTP server ----
// Command serialization: all mutations to the single live game tab run through
// ONE promise chain. A farm() holds the tab for ~17s; without this, a concurrent
// raw_move/respawn from another caller would interleave and corrupt the world.
let cmdQueue = Promise.resolve();
// Last accept_quest result (questId/giverId/giverPos), surfaced to Python so it
// can persist the turn-in NPC in WorldMemory (the game does not return giverId).
let lastAccept = null;
const server = http.createServer((req, res) => {
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
          health.game = !!page.evaluate(
            () => !!(window.__game && window.__game.sim && window.__game.sim.player));
        } catch (_) { health.game = false; }
      }
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(health));
      return;
    }
    // simple liveness probe (back-compat)
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, alive: true }));
    return;
  }
  if (req.method !== 'POST') { res.writeHead(405); res.end('use POST'); return; }
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    cmdQueue = cmdQueue.then(async () => {
      let resp = { ok: false };
      try {
        const cmd = JSON.parse(body || '{}');
      if (cmd.action === 'snapshot') {
        // Agent primes its first observation with POST {action:'snapshot'}
        // (browser_env.py __init__). Return the live game snapshot.
        resp = await snap();
      } else if (cmd.action === 'step') {
        await applyAction(cmd.idx || 0, cmd);
        resp = await snap();
        // Surface the giver the agent just accepted from (if this step was accept_quest)
        if (lastAccept && (cmd.idx === 2 || cmd.questId)) {
          resp.giver = lastAccept;
          lastAccept = null;
        }
      } else if (cmd.action === 'navigate') {
        const arrived = await navigateToCoord(cmd.x, cmd.z, cmd.max_steps || 80);
        const base = await snap();
        resp = base.ok ? { ok: true, arrived, info: base.info } : base;
      } else if (cmd.action === 'raw_move') {
        await safeEval((kind) => {
          try { window.__game.controller.stop(); } catch (_) {}
          if (kind === 'forward') window.__game.controller.move({ forward: true });
          else if (kind === 'back') window.__game.controller.move({ back: true });
          else if (kind === 'turnLeft') window.__game.controller.move({ turnLeft: true });
          else if (kind === 'turnRight') window.__game.controller.move({ turnRight: true });
        }, cmd.kind);
        await sleep(TICK_MS);
        resp = await snap();
      } else if (cmd.action === 'respawn') {
        // Death-recovery path (src/sim death recovery): releaseSpirit() FIRST,
        // then resurrectAtSpiritHealer(). resurrectAtCorpse() only works if the
        // player is still physically near the body (not a ghost), so it is useless
        // once dead:true. resurrectAtSpiritHealer() returns a Promise<boolean> over
        // the network (src/net/online.ts) — it does NOT flip player.dead
        // synchronously, so we must await it and then POLL (with a timeout).
        //
        // CRITICAL (recovery-bug fix): we used to fire both calls, swallow the
        // Promise, and always return ok:true. That hid resurrection failures: the
        // agent believed it was alive while the snapshot still showed dead:true,
        // then ran farm/heal/loot on a corpse forever. Now we AWAIT the outcome and
        // POLL player.dead === false && player.hp > 0, and report the real
        // `revived` flag so Python can stop spinning instead of trusting a lie.
        let revived = false;
        const deadBefore = await safeEval(() => !!(window.__game.sim.player && window.__game.sim.player.dead)).catch(() => false);
        if (deadBefore) {
          await safeEval(() => {
            const sim = window.__game.sim;
            try { sim.releaseSpirit(); } catch (_) {}
          });
          // Await the network outcome (resolves false if the server rejects it).
          const okHeal = await safeEval(() => {
            const sim = window.__game.sim;
            if (typeof sim.resurrectAtSpiritHealer === 'function') {
              return sim.resurrectAtSpiritHealer().then(() => true).catch(() => false);
            }
            return false;
          }).catch(() => false);
          // Poll up to ~6s (TICK_MS * 30) for dead:false AND hp>0.
          for (let i = 0; i < 30 && !revived; i++) {
            await sleep(TICK_MS);
            revived = await safeEval(() => {
              const p = window.__game.sim.player;
              return !!(p && !p.dead && (p.hp ?? 0) > 0);
            }).catch(() => false);
          }
          if (!revived) console.error('[bridge] respawn: revival not confirmed (healerOutcome=' + okHeal + ')');
        } else {
          // Not dead on entry — nothing to resurrect; treat as already revived.
          revived = true;
        }
        resp = { ok: true, revived, info: (await snap()).info || {} };
      } else if (cmd.action === 'explore') {
        // sustained walk: head toward nearest mob/NPC (or just forward if none),
        // so the agent actually covers ground instead of 1-step jitter.
        const arrived = await exploreWalk(cmd.steps || 10);
        resp = { ok: true, arrived, info: (await snap()).info || {} };
      } else {
        resp = { ok: false, error: 'unknown action' };
      }
    } catch (e) {
      resp = { ok: false, error: e.message };
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(resp));
    }).catch((e) => {
      try { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify({ ok: false, error: e.message })); } catch (_) {}
    });
  });
});

async function main() {
  if (!await reconnect()) { console.error('[bridge] initial connect failed'); process.exit(1); }
  console.log('[bridge] online game tab ready; serving on :' + PORT);
  server.on('error', (e) => {
    // EADDRINUSE means a previous bridge instance is still holding :PORT.
    // Exit loudly so the launcher's 10s loop can restart us cleanly once the
    // stale instance is gone, instead of silently dying with no log clue.
    console.error('[bridge] server error:', e.code || e.message);
    process.exit(e.code === 'EADDRINUSE' ? 2 : 1);
  });
  server.listen(PORT);
}

main().catch((e) => { console.error('FATAL', e.message); process.exit(1); });
