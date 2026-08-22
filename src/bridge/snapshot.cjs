// src/bridge/snapshot.js
// Builds a FLAT observation object from window.__game.sim. Pure with respect to
// CDP: it receives a GameClient and calls gameClient.evaluate(fn). Returns the
// flat object, or null if the page/game is unavailable. No response wrapping
// here — the caller (actions.js / dispatch) turns null into {ok:false,error}.

const path = require('path');
const fs = require('fs');

// Static Farshore NPC positions + quest -> turn-in NPC, sourced from
// src/sim/content/farshore.ts (FARSHORE_NPCS / FARSHORE_QUESTS). The live game
// does NOT expose sim.questDefs / sim.npcDefs reliably, so we hardcode the
// zone's static layout as a FALLBACK. Priority for turn-in resolution:
//   1. live entity pos (already in q.turnInNpc)
//   2. WorldMemory JSON (python/world_memory.json) — agent persists giver here
//   3. FARSHORE_* static tables (fallback only)
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

// Eastbrook (starting zone, src/sim/content/zone1.ts questIds). Positions are
// a LAST-RESORT fallback only: the live entity positions are authoritative
// (the layout table drifted from the real world — e.g. apothecary_lin is at
// (2.8, 9.7) live vs (11,-3) in the table), so resolveTurnIn prefers
// sim.entities first.
const EASTBROOK_NPC_POS = {
  the_merchant: { x: 0, z: 9.5 },
  marshal_redbrook: { x: 4.5, z: 5.5 },
  trader_wilkes: { x: -7.13, z: 0.81 },
  apothecary_lin: { x: 2.84, z: 9.72 },
  brother_aldric: { x: -16.59, z: -1.4 },
  smith_haldren: { x: 7, z: 16.5 },
  fisherman_brandt: { x: -16, z: 6 },
  foreman_odell: { x: -8, z: -9.5 },
};
const EASTBROOK_QUEST_TURNIN = {
  // marshal_redbrook
  q_wolves: 'marshal_redbrook',
  q_greyjaw: 'marshal_redbrook',
  q_bandits: 'marshal_redbrook',
  q_ringleader: 'marshal_redbrook',
  q_mogger: 'marshal_redbrook',
  // trader_wilkes
  q_boars: 'trader_wilkes',
  q_supplies: 'trader_wilkes',
  // apothecary_lin
  q_spiders: 'apothecary_lin',
  // brother_aldric
  q_bones: 'brother_aldric',
  q_whispers: 'brother_aldric',
  q_names_of_the_dead: 'brother_aldric',
  q_silence_the_call: 'brother_aldric',
  q_rite: 'brother_aldric',
  q_sexton: 'brother_aldric',
  q_hollow: 'brother_aldric',
  q_gravecallers_trail: 'brother_aldric',
  // fisherman_brandt
  q_murlocs: 'fisherman_brandt',
  // foreman_odell
  q_mine: 'foreman_odell',
};

// WorldMemory JSON written by python/memory.py WorldMemory.remember_giver().
function loadWorldMemory() {
  try {
    const p = path.join(__dirname, '..', 'python', 'world_memory.json');
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch (_) {
    return null;
  }
}

// The in-page reader: extracts raw game state. Throws on dead context (caller
// catches via safeEval). Returns a flat object or throws.
function readGameState() {
  const g = window.__game, sim = g.sim, p = sim.player;
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
      questIds: e.questIds || e.questId || null,
    });
  }
  // Real active quests live in sim.questLog (Map<questId, QuestProgress>).
  let active = [], ready = [], done = [];
  const qlog = sim.questLog || (g.world && g.world.questLog) || null;
  const qdefs = sim.questDefs || (g.world && g.world.questDefs) || null;
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
      const entry = { id: qid, state: st, objectives: objs, turnInNpc: null };
      if (st === 'active') active.push(entry);
      else if (st === 'ready') ready.push(entry);
      else if (st === 'done') done.push(entry);
    });
  }
  const inv = (p.inventory || sim.inventory || []);
  // Economy loop (spec 2026-08-22): real inventory ids+counts, known recipes
  // with reagents, craft stations. Known recipes live on
  // g.online.craftingIdentity.knownRecipes (verified live); recipes with full
  // reagent data on sim.recipeList.
  const invFull = inv.map((slot) => ({
    id: slot.itemId || (slot.def && slot.def.id) || null,
    name: slot.name || (slot.def && slot.def.name) || null,
    quality: slot.quality ?? (slot.def ? slot.def.quality : undefined) ?? 0,
    count: slot.count || 1,
  }));
  let knownIds = [];
  try {
    const kr = g.online && g.online.craftingIdentity && g.online.craftingIdentity.knownRecipes;
    if (Array.isArray(kr)) knownIds = kr;
    else if (kr && typeof kr.forEach === 'function') kr.forEach((v) => knownIds.push(v));
  } catch (_) {}
  let recipesKnown = [];
  try {
    const list = sim.recipeList || [];
    const want = new Set(knownIds.map(String));
    for (const r of list) {
      if (want.size && !want.has(String(r.id))) continue;
      recipesKnown.push({
        id: r.id,
        resultItemId: r.resultItemId,
        resultCount: r.resultCount || 1,
        reagents: (r.reagents || []).map((rg) => ({ itemId: rg.itemId, count: rg.count })),
        stationType: r.stationType || null,
      });
    }
  } catch (_) {}
  let stations = [];
  try {
    stations = (sim.stationPlacements || []).map((s) => ({
      id: s.id || s.stationType, stationType: s.stationType || s.type,
      x: s.pos ? s.pos.x : s.x, z: s.pos ? s.pos.z : s.z,
    }));
  } catch (_) {}
  // Mage/caster kit (official classes.ts): resource is p.resource/maxResource
  // ('mana' for mage), abilities come from sim.known[] (ResolvedAbility[]).
  // The agent must SEE its spells and mana or it never uses the class kit.
  const known = (typeof sim.known !== 'undefined') ? (sim.known || []) : [];
  const abilities = [];
  for (let i = 0; i < known.length; i++) {
    const k = known[i];
    if (!k || !k.def || k.def.passive) continue;
    const cd = (p.cooldowns && p.cooldowns.get && p.cooldowns.get(k.def.id)) || 0;
    abilities.push({
      id: k.def.id, name: k.def.name,
      cost: k.cost != null ? k.cost : (k.def.cost || 0),
      castTime: k.castTime != null ? k.castTime : (k.def.castTime || 0),
      cooldown: k.cooldown != null ? k.cooldown : (k.def.cooldown || 0),
      range: k.def.range || 0,
      ready: cd <= 0,
    });
  }
  return {
    player: { hp: p.hp, maxHp: p.maxHp, level: p.level, dead: !!p.dead },
    mana: p.resource, maxMana: p.maxResource,
    abilities,
    player_pos: [p.pos.x, p.pos.z],
    nearby,
    // live NPC positions by templateId — the AUTHORITATIVE turn-in source
    // (static layout tables drifted from the real world). Collected for every
    // npc entity in range; resolveTurnIn checks here FIRST.
    npc_positions: (function () {
      const m = {};
      for (const e of sim.entities.values()) {
        if (e.kind !== 'npc' || !e.templateId || !e.pos) continue;
        m[e.templateId] = { x: e.pos.x, z: e.pos.z };
      }
      return m;
    })(),
    inventory: invFull,
    inventory_by_id: invFull.reduce((m, s) => { if (s.id) m[s.id] = (m[s.id] || 0) + (s.count || 1); return m; }, {}),
    recipes_known: recipesKnown,
    stations,
    quests: { active, ready, done },
    kills: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || p.kills || 0,
    xp: g.online ? g.online.xp : (p.xp || 0),
    copper: sim.copper || 0,
    deaths: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.deaths) || p.deaths || 0,
    quests_done: (typeof (g.online && g.online.questsDone) === 'number') ? g.online.questsDone : done.length,
    in_combat: !!p.inCombat,
  };
}

// Resolve quest turn-in NPC position on the NODE side (FARSHORE_* live in Node
// scope, not the browser context).
function resolveTurnIn(r) {
  if (!r || !r.quests) return r;
  const wm = loadWorldMemory();
  for (const bucket of ['active', 'ready', 'done']) {
    for (const q of (r.quests[bucket] || [])) {
      if (q.turnInNpc) continue;
      let pos = null;
      const wg = wm && wm.quest_givers && wm.quest_givers[q.id];
      if (wg && wg.giver_pos) pos = { x: wg.giver_pos.x, z: wg.giver_pos.z };
      // LIVE entity position is authoritative: static layout tables drifted
      // from the real world (apothecary_lin table (11,-3) vs live (2.8,9.7)),
      // and walking to a stale spot = "Too far away" at the real NPC.
      if (!pos) {
        const turnInId = FARSHORE_QUEST_TURNIN[q.id] || EASTBROOK_QUEST_TURNIN[q.id] || null;
        if (turnInId && r.npc_positions && r.npc_positions[turnInId]) {
          pos = { x: r.npc_positions[turnInId].x, z: r.npc_positions[turnInId].z };
        }
      }
      if (!pos) {
        const turnInId = FARSHORE_QUEST_TURNIN[q.id] || EASTBROOK_QUEST_TURNIN[q.id] || null;
        const npcTable = Object.assign({}, FARSHORE_NPC_POS, EASTBROOK_NPC_POS);
        if (turnInId && npcTable[turnInId]) {
          pos = { x: npcTable[turnInId].x, z: npcTable[turnInId].z };
        }
      }
      if (pos) q.turnInNpc = pos;
    }
  }
  return r;
}

// Build the flat observation. Returns object or null.
async function buildSnapshot(gameClient) {
  if (!gameClient) return null;
  const raw = await gameClient.evaluate(readGameState);
  if (raw == null) return null;
  return resolveTurnIn(raw);
}

module.exports = { buildSnapshot, FARSHORE_NPC_POS, FARSHORE_QUEST_TURNIN, loadWorldMemory };
