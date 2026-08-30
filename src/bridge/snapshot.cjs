// src/bridge/snapshot.js
// Builds a FLAT observation object from window.__game.sim. Pure with respect to
// CDP: it receives a GameClient and calls gameClient.evaluate(fn). Returns the
// flat object, or null if the page/game is unavailable. No response wrapping
// here — the caller (actions.js / dispatch) turns null into {ok:false,error}.

const path = require('path');
const { QUEST_OBJECTIVES } = require('./quest_objectives.cjs');
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
// Полная карта «квест -> NPC сдачи», сгенерированная из zone1.ts.
// Нужна потому, что таблицы ниже покрывают только обычные квесты, а у
// профессиональных (q_prof_*) turnInNpc оставался null -> агент не мог
// дойти до гивера (замер 2026-08-24: loom 6/6, 14 шагов на месте).
const { npcIdForQuest } = require('./quest_turnin.cjs');

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
  // QUEST_OBJECTIVES инлайнятся в тело функции: readGameState сериализуется
  // через .toString() и исполняется ВНУТРИ страницы, где Node-require
  // недоступен (баг 2026-08-25: "QUEST_OBJECTIVES is not defined" ронял
  // весь snapshot -> агент не запускался).
  const QUEST_OBJECTIVES = {"q_prof_intro":[{"type":"gather","nodeType":"ore","count":5}],"q_wolves":[{"type":"kill","targetMobId":"forest_wolf","count":8}],"q_greyjaw":[{"type":"collect","itemId":"greyjaw_fang","count":1}],"q_boars":[{"type":"collect","itemId":"boar_hide","count":5}],"q_spiders":[{"type":"kill","targetMobId":"webwood_spider","count":6},{"type":"collect","itemId":"webwood_silk","count":4}],"q_murlocs":[{"type":"kill","targetMobId":"mudfin_murloc","count":8}],"q_bandits":[{"type":"kill","targetMobId":"vale_bandit","count":10}],"q_prof_workorder_kitchens":[{"type":"collect","itemId":"game_meat","count":8}],"q_prof_workorder_loom":[{"type":"collect","itemId":"spider_silk","count":6}],"q_prof_attune_smith":[{"type":"gather","nodeType":"ore","count":3}],"q_prof_workorder_forge":[{"type":"collect","itemId":"copper_ore","count":8}],"q_prof_workorder_toolworks":[{"type":"collect","itemId":"ironbark_log","count":8}]};
  const g = window.__game, sim = g.sim, p = sim.player;
  const nearby = [];
  for (const e of sim.entities.values()) {
    if (!e.pos) continue;
    const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z;
    const dist = Math.hypot(dx, dz);
    if (dist > 90) continue;
    nearby.push({
      id: e.id, kind: e.kind, type: e.kind, name: e.name,
      x: e.pos.x, z: e.pos.z, hp: e.hp, maxHp: e.maxHp,
      hostile: !!e.hostile, dead: !!e.dead, lootable: !!e.lootable, looted: !!e.looted,
      dist,
      questIds: e.questIds || e.questId || null,
      // vendor marker for the Python sell/buy gate: a merchant is an NPC with a
      // non-empty vendorItems stock (verified live: trader_wilkes vi=13, plain
      // NPCs vi=0). Without this flag sell_junk/buy never become candidates.
      vendor: (e.kind === 'npc' && Array.isArray(e.vendorItems) && e.vendorItems.length > 0),
      vendorItemsCount: (Array.isArray(e.vendorItems) ? e.vendorItems.length : 0),
    });
  }
  // Real active quests live in sim.questLog (Map<questId, QuestProgress>).
  // REQUIRED counts come from qp.resolvedCounts[i] (authoritative, rank/talent
  // resolved — e.g. q_mine needs 10 kills, q_spiders obj2 needs 4), falling back
  // to the def objective count. NEVER qp.counts (that's CURRENT progress) — the
  // old fallback `required: c` made required==current so every quest with any
  // progress looked instantly complete, and quests whose defs aren't in
  // questDefs reported 0/0 forever. That mismatch is what drove the circling:
  // the agent saw "0/0 ACTIVE" on genuinely ready quests and vice versa.
  let active = [], ready = [], done = [];
  const qlog = sim.questLog || (g.world && g.world.questLog) || null;
  const qdefs = sim.questDefs || (g.world && g.world.questDefs) || null;
  if (qlog && typeof qlog.forEach === 'function') {
    qlog.forEach((qp, qid) => {
      const st = qp.state || 'active';
      const def = (qdefs && (qdefs.get ? qdefs.get(qid) : qdefs[qid])) || null;
      const fallback = QUEST_OBJECTIVES[qid] || null;
      // nObj ДОЛЖЕН учитывать fallback: игра не отдаёт questDefs, и если
      // qp.counts пуст, без fallback.length цикл не создаст ни одного
      // objective — агент не видит, что делать (корень «не понимает квесты»).
      const nObj = Math.max((qp.counts || []).length, (def && Array.isArray(def.objectives)) ? def.objectives.length : 0, (fallback && fallback.length) || 0);
      const objs = [];
      for (let i = 0; i < nObj; i++) {
        const o = (def && Array.isArray(def.objectives)) ? def.objectives[i] : null;
        const fb = (fallback && fallback[i]) || null;
        const resolved = qp.resolvedCounts ? qp.resolvedCounts[i] : undefined;
        objs.push({
          type: (o && o.type) || (fb && fb.type) || null,
          itemId: (o && o.itemId) || (fb && fb.itemId) || null,
          nodeType: (o && o.nodeType) || (fb && fb.nodeType) || null,
          targetMobId: (o && o.targetMobId) || (fb && fb.targetMobId) || null,
          current: (qp.counts && qp.counts[i]) || 0,
          required: (resolved != null ? resolved : ((o && o.count != null) ? o.count : (fb && fb.count) || 0)) || 0,
        });
      }
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
    // CANONICAL SCHEMA (P0 fix 2026-08-25): Python consumers (world_state,
    // policy needs_tool, verify_buy) читают slot.itemId. Раньше отдавали
    // "id" -> все проверки has_tool/junk/buy видели None при реальном
    // предмете -> бесконечный buy-saturation.
    itemId: slot.itemId || (slot.def && slot.def.id) || null,
    name: slot.name || (slot.def && slot.def.name) || null,
    // quality: НЕ выдумываем 0. Живой замер — поле undefined у всех слотов;
    // прежний `?? 0` генерировал фейковое quality:0 (== junk в старом
    // детекте). Отдаём null когда игра не даёт данных.
    quality: slot.quality ?? (slot.def ? slot.def.quality : undefined) ?? null,
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
    // Сумки: реальная вместимость из игры (BACKPACK_SLOTS + сумки)
    bags: sim.bags || [],
    bagCapacity: (typeof sim.bagCapacity === 'number') ? sim.bagCapacity : 16,
    nearby,
    // Quest states for all quests offered by nearby NPCs.
    // sim.questState(questId) is AUTHORITATIVE in offline (verified 2026-08-27):
    // returns 'available'|'active'|'done'|'unavailable'. Without this, the agent
    // cannot distinguish "NPC has questIds" from "quest is currently available",
    // which caused the V0 accept_quest loop (givers present but quest unavailable).
    quest_states: (function () {
      const qs = {};
      try {
        for (const e of sim.entities.values()) {
          if (e.kind !== 'npc' || !Array.isArray(e.questIds)) continue;
          for (const qid of e.questIds) {
            if (qid == null || qid in qs) continue;
            try { qs[qid] = sim.questState(qid); } catch (_) { qs[qid] = 'unknown'; }
          }
        }
      } catch (_) {}
      return qs;
    })(),
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
    // --- CANONICAL поля для детектора прогресса (аудит P0.2/P0.4) ---
    // inventory_by_id (ниже) уже даёт {itemId: count} — именно его надо
    // диффить: free_slots СЛЕПЫ к стакам (handaxe x1 -> x2 не меняет число
    // слотов), из-за чего реальная покупка классифицировалась как NO_OP.
    // 1) экипировка как {slot: itemId}. equipment_rev в observation не
    //    формировался, поэтому контракт equip -> equipment_changed был слепым.
    equipment: (function () {
      try {
        const w = g.world;
        const pp = w && w.players && w.primaryId != null
          ? w.players.get(w.primaryId) : null;
        const eq = pp && pp.equipment;
        if (!eq) return {};
        const out = {};
        for (const k of Object.keys(eq)) {
          const v = eq[k];
          out[k] = (v && typeof v === 'object') ? (v.itemId || v.id || null) : v;
        }
        return out;
      } catch (_) { return {}; }
    })(),
    // 3) ассортимент и ЦЕНЫ ближайшего вендора (items.ts: buyValue).
    //    money_sufficient = copper > 0 пропускало покупку handaxe (buyValue 20)
    //    при copper 14 -> гарантированный failure и мусорный transition.
    vendor_offers: (function () {
      try {
        let best = null, bd = Infinity;
        for (const e of sim.entities.values()) {
          if (!e || !e.pos || !e.vendorItems || !e.vendorItems.length) continue;
          const d = Math.hypot(e.pos.x - p.pos.x, e.pos.z - p.pos.z);
          if (d < bd) { bd = d; best = e; }
        }
        if (!best) return null;
        const defs = (typeof sim.itemDef === 'function') ? sim.itemDef.bind(sim) : null;
        const items = [];
        for (const id of best.vendorItems) {
          let price = null;
          try {
            const def = defs ? defs(id) : null;
            if (def) price = (def.buyValue != null) ? def.buyValue : (def.sellValue != null ? def.sellValue : null);
          } catch (_) {}
          items.push({ itemId: id, price: price });
        }
        return { npc: best.templateId || best.name || null, dist: bd, items: items };
      } catch (_) { return null; }
    })(),
    inventory_by_id: invFull.reduce((m, s) => { if (s.itemId) m[s.itemId] = (m[s.itemId] || 0) + (s.count || 1); return m; }, {}),
    recipes_known: recipesKnown,
    stations,
    quests: { active, ready, done },
    kills: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || p.kills || 0,
    xp: g.online ? g.online.xp : (p.xp || 0),
    copper: sim.copper || 0,
    deaths: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.deaths) || p.deaths || 0,
    // Честный счётчик сданных квестов (см. quests_done.cjs + тесты):
    // online.questsDone — это Set, поэтому прежняя проверка
    // `typeof === 'number'` всегда была ложной и счётчик вечно показывал 0,
    // хотя квесты РЕАЛЬНО сдавались (замер: Set(7)). Верификатор считал
    // каждую успешную сдачу провалом.
    // ВНИМАНИЕ: этот блок исполняется ВНУТРИ страницы, require() здесь не
    // работает (первая попытка через questsDoneCount() падала с
    // "questsDoneCount is not defined"). Логика продублирована инлайном;
    // источник истины и тесты — src/bridge/quests_done.cjs + test_quests_done.cjs.
    quests_done: (function () {
      const fallback = done.length;
      const qd = g.online ? g.online.questsDone : undefined;
      let fromOnline = null;
      if (typeof qd === 'number') fromOnline = qd;
      else if (qd && typeof qd.size === 'number') fromOnline = qd.size;   // Set
      else if (Array.isArray(qd)) fromOnline = qd.length;
      return fromOnline === null ? fallback : Math.max(fromOnline, fallback);
    })(),
    // Кулдаун повторяемых work-order квестов: сервер мирроринг через cprof.
    // Без него агент пытается снова взять квест, который в кулдауне.
    quest_cadence_blocked: (function () {
      try {
        const ci = g.online && g.online.craftingIdentity;
        const set = ci && ci.cadenceBlockedQuests;
        return set ? Array.from(set) : [];
      } catch (_) { return []; }
    })(),
    in_combat: !!p.inCombat,
    // Класс персонажа ИЗ ИГРЫ (sim.entities -> kind==='player' -> templateId).
    // Нужен политике: warrior бьётся вплотную, mage/hunter кайтят. Без этого
    // агент играл магом за воина (probe 2026-08-26: templateId === 'warrior').
    player_class: (function () {
      try {
        if (p.templateId) return p.templateId;
        for (const e of sim.entities.values()) {
          if (e && e.kind === 'player') return e.templateId || e.class || null;
        }
      } catch (_) {}
      return null;
    })(),
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
      // id гивера: сначала сгенерированная из zone1.ts карта (покрывает
      // профессиональные квесты), затем прежние статические таблицы.
      const turnInId = npcIdForQuest(q.id)
        || FARSHORE_QUEST_TURNIN[q.id] || EASTBROOK_QUEST_TURNIN[q.id] || null;
      // ЖИВАЯ позиция сущности авторитетна: статические таблицы дрейфуют
      // (apothecary_lin в таблице (11,-3) против живых (2.8,9.7)), а поход в
      // устаревшую точку = "Too far away." у настоящего NPC.
      if (!pos && turnInId && r.npc_positions && r.npc_positions[turnInId]) {
        pos = { x: r.npc_positions[turnInId].x, z: r.npc_positions[turnInId].z };
      }
      if (!pos && turnInId) {
        const npcTable = Object.assign({}, FARSHORE_NPC_POS, EASTBROOK_NPC_POS);
        if (npcTable[turnInId]) {
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
