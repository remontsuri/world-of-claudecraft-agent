// browser_bridge_offline.cjs — офлайн WoC (localhost:5173) <-> Python agent bridge.
// Основан на основном мосте проекта: полный набор действий с questId,
// navigateToCoord, per-class chase, honest вердикты.

const { connect } = require('puppeteer-core');
const http = require('http');
const EXPORT = JSON.parse(require('fs').readFileSync('D:/world-of-claudecraft/python/game_agent_export.json', 'utf-8'));
const QUEST_OBJECTIVES = EXPORT.quest_objectives || {};

const CDP = 'http://127.0.0.1:9222';
const PORT = 8791;
const TICK_MS = 220;

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

let browser = null;
let page = null;

async function safeEval(fn, ...args) {
  if (!page) throw new Error('no page');
  try { await page.bringToFront(); } catch (_) {}
  return await page.evaluate(fn, ...args);
}

async function reconnect() {
  try {
    if (browser) { try { await browser.disconnect(); } catch (_) {} }
    browser = await connect({ browserURL: CDP });
    for (const p of await browser.pages()) {
      const u = (typeof p.url === 'function') ? p.url() : (p.url || '');
      if (u.includes('worldofclaudecraft') || u.includes('localhost:5173')) { page = p; break; }
    }
    if (!page) { console.error('[bridge] no game tab'); return false; }
    await page.bringToFront();
    await page.waitForFunction(
      '!!window.__game && !!window.__game.sim && !!window.__game.sim.player',
      { timeout: 60000 }
    );
    console.log('[bridge] connected to offline game tab');
    return true;
  } catch (e) {
    console.error('[bridge] connect failed:', e.message);
    page = null;
    return false;
  }
}

// ---- snapshot ----
async function buildSnapshot() {
  // QUEST_OBJECTIVES инлайнятся: safeEval сериализует функцию в контекст
  // браузера, где Node-require недоступен (та же ошибка что в онлайне fd99334)
  const QUEST_OBJECTIVES_JSON = JSON.stringify(QUEST_OBJECTIVES);
  console.log('[SNAP-DBG] QO_JSON type:', typeof QUEST_OBJECTIVES_JSON, '. safeEval args will pass');
    return await safeEval((QO_JSON) => {
    const QUEST_OBJECTIVES = JSON.parse(QO_JSON);
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
        vendor: (e.kind === 'npc' && Array.isArray(e.vendorItems) && e.vendorItems.length > 0),
      });
    }
    let active = [], ready = [], done = [];
    const qlog = sim.questLog || (g.world && g.world.questLog) || null;
    if (qlog && typeof qlog.forEach === 'function') {
      qlog.forEach((qp, qid) => {
        const st = qp.state || 'active';
        // Офлайн-клиент не отдаёт objectives в questLog — обогащаем из таблицы.
        // counts[i] = текущий прогресс, resolvedCounts[i] = required (авторитетно).
        const fb = QUEST_OBJECTIVES[String(qid)] || [];
        const objectives = (qp.objectives && qp.objectives.length) ? qp.objectives.map(o => ({
          type: o.type || null, itemId: o.itemId || null,
          targetMobId: o.targetMobId || o.mobId || null, nodeType: o.nodeType || null,
          current: o.current || o.count || 0, required: o.required || o.need || 0,
        })) : fb.map((o, i) => ({
          type: o.type || null, itemId: o.itemId || null,
          targetMobId: o.targetMobId || null, nodeType: o.nodeType || null,
          current: (qp.counts && qp.counts[i]) || 0,
          required: (qp.resolvedCounts && qp.resolvedCounts[i] != null) ? qp.resolvedCounts[i] : (o.count || 0),
        }));
        const entry = {
          id: String(qid), state: st,
          objectives,
          turnInNpc: null,
        };
        if (st === 'active') active.push(entry);
        else if (st === 'ready') ready.push(entry);
        else done.push(entry);
      });
    }
    const inv = (p.inventory || sim.inventory || []);
    const invFull = inv.map((slot) => ({
      itemId: slot.itemId || (slot.def && slot.def.id) || null,
      name: slot.name || (slot.def && slot.def.name) || null,
      quality: slot.quality ?? (slot.def ? slot.def.quality : undefined) ?? null,
      count: slot.count || 1,
    }));
    const questsDone = (() => {
      const qd = g.online ? g.online.questsDone : undefined;
      if (typeof qd === 'number') return qd;
      if (qd && typeof qd.size === 'number') return qd.size;
      if (Array.isArray(qd)) return qd.length;
      if (g.world && g.world.questsDone && typeof g.world.questsDone.size === 'number') return g.world.questsDone.size;
      return done.length;
    })();
    return {
      ok: true,
      player: { hp: p.hp ?? p.health ?? 100, maxHp: p.maxHp || p.hpMax || 100, level: p.level || 1, dead: !!p.dead },
      mana: p.mana ?? 0, maxMana: p.maxMana ?? 0,
      player_pos: [+(p.pos.x.toFixed(3)), +(p.pos.z.toFixed(3))],
      nearby,
      inventory: invFull,
      inventory_by_id: invFull.reduce((m, s) => { if (s.itemId) m[s.itemId] = (m[s.itemId] || 0) + (s.count || 1); return m; }, {}),
      bagCapacity: 26,
      quests: { active, ready, done },
      quests_done: questsDone,
      kills: (sim.deedStats && sim.deedStats.counters && sim.deedStats.counters.kills) || p.kills || 0,
      xp: g.online ? g.online.xp : (g.world.xp || p.xp || 0),
      copper: g.world.copper !== undefined ? g.world.copper : (p.copper || 0),
      deaths: p.deaths || 0,
      in_combat: !!p.inCombat,
      recipes_known: [],
      stations: [],
    };
  }).catch(e => { console.error('[snapshot]', String(e).slice(0, 80)); return null; });
}

// ---- navigate ----
async function navigateToCoord(tx, tz, maxSteps) {
  let arrived = false;
  for (let i = 0; i < (maxSteps || 80); i++) {
    const st = await safeEval((tx, tz) => {
      const g = window.__game, p = g.sim.player;
      const dx = tx - p.pos.x, dz = tz - p.pos.z, d = Math.hypot(dx, dz);
      const desired = Math.atan2(dx, dz);
      try { g.controller.face(desired); } catch (_) {}
      if (d < 4) { try { g.controller.stop(); } catch (_) {} return { arrived: true, d }; }
      g.controller.move({ forward: true });
      return { arrived: false, d };
    }, tx, tz);
    if (st && st.arrived) { arrived = true; break; }
    await sleep(TICK_MS);
  }
  await safeEval(() => { try { window.__game.controller.stop(); } catch (_) {} });
  return arrived;
}

// ---- actions ----
let gatherNoTarget = false;

async function applyAction(idx, cmd, gameClient) {
  gatherNoTarget = false;
  switch (idx) {
    case 0: { // farm
      const questMobId = (cmd && cmd.targetMobId) || null;
      const targetId = await safeEval((qm) => {
        const g = window.__game, sim = g.sim, p = sim.player;
        let best = null, bd = Infinity, qb = null, qbd = Infinity;
        for (const e of sim.entities.values()) {
          if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0 || e.hostile === false) continue;
          const tid = e.templateId || e.mobId || null;
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          if (d > 60) continue;
          if (d < bd) { bd = d; best = e; }
          if (qm && tid === qm && d < qbd) { qbd = d; qb = e; }
        }
        return qb ? qb.id : (best ? best.id : null);
      }, questMobId);
      if (targetId == null) { gatherNoTarget = true; break; }
      for (let t = 0; t < 40; t++) {
        const st = await safeEval((id) => {
          const g = window.__game, sim = g.sim, p = sim.player;
          const e = sim.entities.get(id);
          if (!e || e.dead || (e.hp ?? 0) <= 0) return { gone: true };
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          const desired = Math.atan2(dx, dz);
          // mage ranged stop ~27 yd
          try { g.controller.face(desired); } catch (_) {}
          if (d > 27) { g.controller.move({ forward: true }); return { d, chase: true }; }
          try { g.controller.stop(); } catch (_) {}
          try { sim.targetEntity(id); } catch (_) {}
          try { sim.startAutoAttack(); } catch (_) {}
          try { if (typeof sim.castAbilityOn === 'function') sim.castAbilityOn(id, 0); } catch (_) {}
          return { d, attack: true };
        }, targetId);
        if (st && st.gone) break;
        await sleep(TICK_MS);
      }
      break;
    }
    case 1: // loot
      await safeEval(() => { try { window.__game.sim.interact(); } catch (_) {} });
      break;
    case 2: { // accept_quest(qid) — С НАВИГАЦИЕЙ К ГИВЕРУ
      const qid = (cmd && cmd.questId) || null;
      const npcId = (cmd && cmd.npcId) || null;
      // PLAN-STACK: accept требует dist <= 7 yd от гивера (quest_commands.ts:148
      // INTERACT_RANGE+2). Сначала ищем гивера квеста, идём к нему, потом accept.
      const giverPos = await safeEval((qid) => {
        const g = window.__game, sim = g.sim, p = sim.player;
        // ищем NPC с этим квестом (или заданного npcId)
        let best = null, bd = Infinity;
        for (const e of sim.entities.values()) {
          if (e.kind !== 'npc') continue;
          if (npcId != null && String(e.id) === String(npcId)) { best = e; break; }
          const qids = e.questIds || [];
          if (qid && qids.includes(String(qid))) {
            const d = Math.hypot(e.pos.x - p.pos.x, e.pos.z - p.pos.z);
            if (d < bd) { bd = d; best = e; }
          }
        }
        if (!best) return { none: true };
        return { x: best.pos.x, z: best.pos.z, id: best.id, d: bd };
      }, qid);
      if (giverPos && giverPos.none) { gatherNoTarget = true; break; }
      if (giverPos && giverPos.d > 6) {
        await navigateToCoord(page, giverPos.x, giverPos.z, 120);
      }
      await safeEval((qid) => {
        try { window.__game.sim.acceptQuest(String(qid)); } catch (_) {}
      }, qid);
      break;
    }
    case 3: { // turn_in_quest(qid) — тоже с навигацией (тот же INTERACT_RANGE)
      const qid = (cmd && cmd.questId) || null;
      const giverPos = await safeEval((qid) => {
        const g = window.__game, sim = g.sim, p = sim.player;
        let best = null, bd = Infinity;
        for (const e of sim.entities.values()) {
          if (e.kind !== 'npc') continue;
          const qids = e.questIds || [];
          // turn-in NPC может не иметь questIds — берём любого близкого NPC если qid неизвестен
          if (qid && !qids.length && best) continue;
          const d = Math.hypot(e.pos.x - p.pos.x, e.pos.z - p.pos.z);
          if (d < bd) { bd = d; best = e; }
        }
        if (!best) return { none: true };
        return { x: best.pos.x, z: best.pos.z, d: bd };
      }, qid);
      if (giverPos && giverPos.none) { gatherNoTarget = true; break; }
      if (giverPos && giverPos.d > 6) {
        await navigateToCoord(page, giverPos.x, giverPos.z, 120);
      }
      await safeEval((qid) => {
        try { window.__game.sim.turnInQuest(String(qid)); } catch (_) {}
      }, qid);
      break;
    }
    case 4: // sell_junk
      await safeEval(() => {
        try { window.__game.sim.interact(); } catch (_) {}
        try { window.__game.sim.sellAllJunk && window.__game.sim.sellAllJunk(); } catch (_) {}
      });
      break;
    case 5: { // gather: navigate to nearest static/live node then harvest
      const wantType = (cmd && cmd.nodeType) || null;
      const NODES = {
        ore_eastbrook_1: { type: 'ore', x: -70, z: -53 },
        ore_eastbrook_6: { type: 'ore', x: -65, z: -69 },
        wood_eastbrook_1: { type: 'wood', x: -62, z: 8 },
        wood_eastbrook_2: { type: 'wood', x: -57, z: -6 },
        herb_eastbrook_1: { type: 'herb', x: -59, z: 91 },
      };
      let target = null, bd = Infinity;
      for (const [nid, n] of Object.entries(NODES)) {
        if (wantType && n.type !== wantType) continue;
        const d = await safeEval((nx, nz) => Math.round(Math.hypot(nx - window.__game.sim.player.pos.x, nz - window.__game.sim.player.pos.z)), n.x, n.z);
        if (d < bd) { bd = d; target = { id: nid, x: n.x, z: n.z }; }
      }
      if (!target) { gatherNoTarget = true; break; }
      const arrived = await navigateToCoord(gameClient || page, target.x, target.z, 120);
      if (!arrived) { gatherNoTarget = true; break; }
      await safeEval((id) => { try { window.__game.sim.harvestNode(String(id)); } catch (_) {} }, target.id);
      for (let i = 0; i < 15; i++) {
        await sleep(TICK_MS);
        const casting = await safeEval(() => !!window.__game.sim.player.castingAbility).catch(() => false);
        if (!casting) break;
      }
      break;
    }
    case 6: // craft — не реализовано офлайн
      break;
    case 7: // heal
      await safeEval(() => {
        const g = window.__game, sim = g.sim;
        try { sim.interact(); } catch (_) {}
      });
      break;
    case 8: // equip
      await safeEval(() => {
        const g = window.__game, sim = g.sim;
        const inv = sim.inventory;
        const list = inv instanceof Map ? Array.from(inv.values()) : (Array.isArray(inv) ? inv : []);
        for (const slot of list) {
          if (!slot) continue;
          try { sim.equipItem(slot.itemId || slot.id); break; } catch (_) {}
        }
      });
      break;
    case 9: { // buy(itemId) у ближайшего вендора
      const itemId = (cmd && cmd.buyItemId) || null;
      let v = null;
      for (let attempt = 0; attempt < 3 && v == null; attempt++) {
        v = await safeEval((wanted) => {
          const g = window.__game, sim = g.sim, p = sim.player;
          let best = null, bd = Infinity;
          for (const e of sim.entities.values()) {
            if ((e.kind === 'npc') && Array.isArray(e.vendorItems) && e.vendorItems.length > 0) {
              const d = Math.hypot(e.pos.x - p.pos.x, e.pos.z - p.pos.z);
              if (d < bd) { bd = d; best = { id: e.id, x: e.pos.x, z: e.pos.z }; }
            }
          }
          if (!best) return { none: true };
          if (bd > 5) return { far: true, x: best.x, z: best.z };
          try { sim.buyItem(best.id, wanted); return { ok: best.id }; } catch (_) {}
          return { far: true, x: best.x, z: best.z };
        }, itemId);
        if (v && v.none) break;
        if (v && v.far) await navigateToCoord(page, v.x, v.z, 60);
      }
      if (!v || v.none) gatherNoTarget = true;
      break;
    }
    default:
      await safeEval(() => { try { window.__game.controller.stop(); } catch (_) {} });
  }
  await sleep(TICK_MS);
  return { noTarget: gatherNoTarget };
}

// ---- HTTP server ----
const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, bridge: !!browser, page: !!page, game: !!(page) }));
    return;
  }
  if (req.method !== 'POST') { res.writeHead(405); res.end('use POST'); return; }
  let body = '';
  req.on('data', c => body += c);
  req.on('end', async () => {
    let msg = {};
    try { msg = JSON.parse(body || '{}'); } catch (_) {}
    if (msg.action === 'snapshot') {
      if (!page) { const okr = await reconnect(); if (!okr) { res.writeHead(503); res.end(JSON.stringify({ ok: false })); return; } }
      const snap = await buildSnapshot();
      if (!snap) { res.writeHead(500); res.end(JSON.stringify({ ok: false })); return; }
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: true, info: snap }));
      return;
    }
    if (msg.action === 'step') {
      if (!page) { const okr = await reconnect(); if (!okr) { res.writeHead(503); res.end(JSON.stringify({ ok: false })); return; } }
      const result = await applyAction(msg.idx | 0, msg.cmd || {}, page);
      const snap = await buildSnapshot();
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: true, noTarget: result.noTarget, info: snap }));
      return;
    }
    res.writeHead(400); res.end(JSON.stringify({ ok: false, err: 'unknown action' }));
  });
});

(async () => {
  const ok = await reconnect();
  if (!ok) { console.error('[bridge] initial connect failed'); process.exit(1); }
  server.listen(PORT, () => console.log(`[bridge] serving on :${PORT}`));
})();
