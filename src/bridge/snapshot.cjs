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
    inventory: inv.map((it) => ({ quality: it.quality ?? 0, name: it.name })),
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
      if (!pos) {
        const turnInId = FARSHORE_QUEST_TURNIN[q.id] || null;
        if (turnInId && FARSHORE_NPC_POS[turnInId]) {
          pos = { x: FARSHORE_NPC_POS[turnInId].x, z: FARSHORE_NPC_POS[turnInId].z };
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
