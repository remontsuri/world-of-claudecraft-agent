// src/bridge/actions.js
// Command handlers. Each returns a NORMALIZED response:
//   { ok: true,  info: <flat snapshot>, ...extra }   on success
//   { ok: false, error: <string> }                   on failure
// `info` is ALWAYS the flat observation from buildSnapshot (or null -> error).
// No nested {ok,info:{ok,info}}. Game semantics (farm/heal/loot/nav/respawn)
// live here; transport lives in game_client.js; observation in snapshot.js.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Last accept_quest result (questId/giverPos), surfaced to Python so it can
// persist the turn-in NPC in WorldMemory (the game does not return giverId).
let lastAccept = null;
function setLastAccept(v) { lastAccept = v; }

// ---- internal game helpers (run in page context) ----

// step idx MUST match python SKILLS order (hierarchical_env.py):
// 0=farm 1=loot 2=accept_quest 3=turn_in_quest 4=sell_junk 5=gather 6=craft
// 7=heal 8=equip 9=buy. Each case uses the REAL client API; unsupported
// capabilities are honest no-ops with a console warning (no fake success).
async function applyAction(idx, cmd, gameClient) {
  switch (idx) {
    case 0: { // farm: chase + attack nearest HOSTILE living mob until it dies
      const targetId = await gameClient.evaluate(() => {
        const g = window.__game, sim = g.sim, p = sim.player;
        let best = null, bd = Infinity;
        for (const e of sim.entities.values()) {
          if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0) continue;
          if (e.hostile === false) continue; // peaceful NPC (quest giver / villager)
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          if (d <= 120 && d < bd) { bd = d; best = e; }
        }
        return best ? best.id : null;
      });
      if (targetId == null) break; // no hostile mob in range: inconclusive, not an error
      for (let t = 0; t < 80; t++) {
        const st = await gameClient.evaluate((id) => {
          const g = window.__game, sim = g.sim, p = sim.player;
          const e = sim.entities.get(id);
          if (!e || e.dead || (e.hp ?? 0) <= 0) return { gone: true };
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          if (d > 7) {
            const desired = Math.atan2(dx, dz);
            let off = desired - p.facing;
            off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
            if (Math.abs(off) > 0.2) {
              if (off > 0) g.controller.move({ turnLeft: true, forward: true });
              else g.controller.move({ turnRight: true, forward: true });
            } else { g.controller.move({ forward: true }); }
            return { d, phase: 'chase' };
          }
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
        if (st && st.gone) break;
        await sleep(gameClient.tickMs);
      }
      break;
    }
    case 1: // loot: interact() loots the targeted lootable corpse in this client
      await gameClient.evaluate(() => { try { window.__game.sim.interact(); } catch (_) {} });
      break;
    case 2: { // accept_quest: accept the SPECIFIC quest via sim.acceptQuest(qid)
      const qid = (cmd && cmd.questId) || null;
      // Capture the giver (NPC id + live position) so Python can persist it in
      // WorldMemory. The live game does NOT return giverId in sim.questLog.
      const npcId = (cmd && cmd.npcId) || null;
      let giverPos = null;
      if (npcId) {
        giverPos = await gameClient.evaluate((id) => {
          const sim = window.__game.sim;
          for (const e of sim.entities.values()) {
            if (String(e.id) === String(id) && e.pos) return { x: e.pos.x, z: e.pos.z };
          }
          return null;
        }, npcId).catch(() => null);
      }
      lastAccept = { questId: qid, giverId: npcId, giverPos };
      if (qid) {
        await gameClient.evaluate((id) => { try { window.__game.sim.acceptQuest(String(id)); } catch (_) {} }, qid);
      } else {
        // fallback: bare interact() (legacy path, inconclusive in this build)
        await gameClient.evaluate(() => { try { window.__game.sim.interact(); } catch (_) {} });
      }
      break;
    }
    case 3: { // turn_in_quest: turn in the specific ready quest
      const qid = (cmd && cmd.questId) || null;
      if (qid) {
        await gameClient.evaluate((id) => { try { window.__game.sim.turnInQuest(String(id)); } catch (_) {} }, qid);
      } else {
        await gameClient.evaluate(() => { try { window.__game.sim.interact(); } catch (_) {} });
      }
      break;
    }
    case 4: { // sell_junk: only works next to a vendor NPC (guarded)
      const hasVendor = await gameClient.evaluate(() => {
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
        await gameClient.evaluate(() => {
          try { window.__game.sim.interact(); } catch (_) {}
          try { window.__game.sim.sellAllJunk && window.__game.sim.sellAllJunk(); } catch (_) {}
        });
      }
      break;
    }
    case 5: { // gather: harvest the nearest harvestable node within range
      const nodeId = await gameClient.evaluate(() => {
        const g = window.__game, sim = g.sim, p = sim.player;
        let best = null, bd = Infinity;
        for (const e of sim.entities.values()) {
          const isNode = (e.kind === 'gather_node' || e.nodeType || e.gatherTier !== undefined);
          if (!isNode || e.dead || e.depleted) continue;
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          if (d <= 60 && d < bd) { bd = d; best = e.id; }
        }
        return best != null ? best : null;
      });
      if (nodeId != null) {
        await gameClient.evaluate((id) => { try { window.__game.sim.harvestNode(String(id)); } catch (_) {} }, nodeId);
      }
      break;
    }
    case 6: // craft — NOT exposed in the live client (sim.craft undefined).
      console.warn('[actions] craft requested but sim.craft is not exposed -> unsupported');
      break;
    case 7: { // heal: use the first health potion in the bag (if any)
      const used = await gameClient.evaluate(() => {
        const sim = window.__game.sim;
        const inv = sim.inventory;
        const list = inv instanceof Map ? Array.from(inv.values()) : (Array.isArray(inv) ? inv : []);
        for (const slot of list) {
          if (!slot) continue;
          const def = slot.def || slot.itemDef || {};
          const name = (def.name || '').toLowerCase();
          const id = slot.itemId || def.id;
          if (!id) continue;
          if (/potion|draught|tonic|elixir|heal/i.test(name)) {
            try { sim.useItem(id); return true; } catch (_) { return false; }
          }
        }
        return false;
      });
      if (!used) console.warn('[actions] heal requested but no potion in bag -> no-op');
      break;
    }
    case 8: { // equip: equip the first unequipped gear item (if any)
      const equipped = await gameClient.evaluate(() => {
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
      if (!equipped) console.warn('[actions] equip requested but nothing equippable -> no-op');
      break;
    }
    case 9: { // buy: buy a health potion from a nearby vendor (guarded)
      const DEFAULT_BUY = 'minor_healing_potion';
      const v = await gameClient.evaluate((itemId) => {
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
      if (v == null) console.warn('[actions] buy requested but no vendor in range -> no-op');
      break;
    }
    default:
      await gameClient.evaluate(() => { try { window.__game.controller.stop(); } catch (_) {} });
  }
  await sleep(gameClient.tickMs);
}

// Walk toward (x,z); returns arrived bool. Geometry (measured live):
// player.facing=0 -> +Z; turnLeft INCREASES facing, turnRight DECREASES it;
// forward moves along (sin(facing), cos(facing)) -> desired = atan2(dx, dz).
// ALWAYS stops the controller on arrive AND on timeout (no inertia running).
async function navigateToCoord(gameClient, x, z, maxSteps) {
  let arrived = false;
  for (let i = 0; i < (maxSteps || 80); i++) {
    const st = await gameClient.evaluate((tx, tz) => {
      const g = window.__game, p = g.sim.player;
      const dx = tx - p.pos.x, dz = tz - p.pos.z, d = Math.hypot(dx, dz);
      if (d < 5) { try { g.controller.stop(); } catch (_) {} return { arrived: true, d }; }
      const desired = Math.atan2(dx, dz);
      let off = desired - p.facing;
      off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
      if (Math.abs(off) > 0.2) {
        if (off > 0) g.controller.move({ turnLeft: true, forward: true });
        else g.controller.move({ turnRight: true, forward: true });
      } else { g.controller.move({ forward: true }); }
      return { arrived: false, d };
    }, x, z);
    if (st && st.arrived) { arrived = true; break; }
    await sleep(gameClient.tickMs);
  }
  if (!arrived) {
    await gameClient.evaluate(() => { try { window.__game.controller.stop(); } catch (_) {} });
  }
  return arrived;
}

// Sustained walk: plain forward + turn every 7th step. Target-seeking was
// VERIFIED LIVE to make the agent jitter in place; plain forward actually
// covers ground (raw_move moves ~13yd per 5 calls).
async function exploreWalk(gameClient, steps) {
  for (let i = 0; i < (steps || 10); i++) {
    const turn = (i % 7 === 6);
    await gameClient.evaluate((t) => {
      try { window.__game.controller.stop(); } catch (_) {}
      if (t) {
        try { window.__game.controller.move({ turnLeft: true, forward: true }); } catch (_) {}
      } else {
        try { window.__game.controller.move({ forward: true }); } catch (_) {}
      }
    }, turn);
    await sleep(gameClient.tickMs);
  }
  return true;
}

// ---- handler factory (binds gameClient + buildSnapshot) ----

function createActions({ gameClient, buildSnapshot, tickMs = 220 }) {
  // bind helpers that capture gameClient
  const apply = (idx, cmd) => applyAction(idx, cmd, gameClient);
  const navigate = (x, z, ms) => navigateToCoord(gameClient, x, z, ms);
  const explore = (s) => exploreWalk(gameClient, s);

  async function snapshotHandler() {
    const r = await buildSnapshot(gameClient);
    if (r == null) return { ok: false, error: 'snapshot failed (no game tab / not ready)' };
    return { ok: true, info: r };
  }

  async function stepHandler(cmd) {
    await apply(cmd.idx || 0, cmd);
    const r = await buildSnapshot(gameClient);
    if (r == null) return { ok: false, error: 'snapshot after step failed' };
    const out = { ok: true, info: r };
    if (lastAccept && (cmd.idx === 2 || cmd.questId)) {
      out.giver = lastAccept;
      lastAccept = null;
    }
    return out;
  }

  async function navigateHandler(cmd) {
    const arrived = await navigate(cmd.x, cmd.z, cmd.max_steps || 80);
    const r = await buildSnapshot(gameClient);
    if (r == null) return { ok: false, error: 'snapshot after navigate failed' };
    return { ok: true, arrived, info: r };
  }

  async function rawMoveHandler(cmd) {
    await gameClient.evaluate((kind) => {
      try { window.__game.controller.stop(); } catch (_) {}
      if (kind === 'forward') window.__game.controller.move({ forward: true });
      else if (kind === 'back') window.__game.controller.move({ back: true });
      else if (kind === 'turnLeft') window.__game.controller.move({ turnLeft: true });
      else if (kind === 'turnRight') window.__game.controller.move({ turnRight: true });
    }, cmd.kind);
    await sleep(tickMs);
    const r = await buildSnapshot(gameClient);
    if (r == null) return { ok: false, error: 'snapshot after raw_move failed' };
    return { ok: true, info: r };
  }

  async function respawnHandler() {
    let revived = false;
    const deadBefore = await gameClient.evaluate(() =>
      !!(window.__game.sim.player && window.__game.sim.player.dead)).catch(() => false);
    if (deadBefore) {
      await gameClient.evaluate(() => {
        const sim = window.__game.sim;
        try { sim.releaseSpirit(); } catch (_) {}
      });
      await gameClient.evaluate(() => {
        const sim = window.__game.sim;
        if (typeof sim.resurrectAtSpiritHealer === 'function') {
          return sim.resurrectAtSpiritHealer().then(() => true).catch(() => false);
        }
        return false;
      }).catch(() => false);
      for (let i = 0; i < 30 && !revived; i++) {
        await sleep(tickMs);
        revived = await gameClient.evaluate(() => {
          const p = window.__game.sim.player;
          return !!(p && !p.dead && (p.hp ?? 0) > 0);
        }).catch(() => false);
      }
      if (!revived) console.error('[actions] respawn: revival not confirmed');
    } else {
      revived = true; // not dead on entry — nothing to resurrect
    }
    const r = await buildSnapshot(gameClient);
    if (r == null) return { ok: false, error: 'snapshot after respawn failed' };
    return { ok: true, revived, info: r };
  }

  async function exploreHandler(cmd) {
    const arrived = await explore(cmd.steps || 10);
    const r = await buildSnapshot(gameClient);
    if (r == null) return { ok: false, error: 'snapshot after explore failed' };
    return { ok: true, arrived, info: r };
  }

  return {
    snapshot: snapshotHandler,
    step: stepHandler,
    navigate: navigateHandler,
    raw_move: rawMoveHandler,
    respawn: respawnHandler,
    explore: exploreHandler,
  };
}

module.exports = { createActions, applyAction, navigateToCoord, exploreWalk };
