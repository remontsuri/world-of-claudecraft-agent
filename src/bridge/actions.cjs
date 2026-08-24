// src/bridge/actions.js
// Command handlers. Each returns a NORMALIZED response:
//   { ok: true,  info: <flat snapshot>, ...extra }   on success
//   { ok: false, error: <string> }                   on failure
// `info` is ALWAYS the flat observation from buildSnapshot (or null -> error).
// No nested {ok,info:{ok,info}}. Game semantics (farm/heal/loot/nav/respawn)
// live here; transport lives in game_client.js; observation in snapshot.js.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Анти-рыскание камеры (баг, замеченный пользователем 2026-08-24, повторно).
// ПЕРВЫЙ фикс закрыл только navigateToCoord, но камерой дёргает в основном
// case 0 (farm) — он крутится до 80 итераций и применял порог 0.2 рад дважды
// (chase + face). Единый порог = автоколебание: курс проскакивает нуль, знак
// ошибки меняется, камера ходит влево-вправо каждый тик.
// Лечение: ГИСТЕРЕЗИС (вход 0.35 рад / выход 0.10 рад) + память состояния в
// window.__navTurning. Логика продублирована в src/bridge/heading.cjs, где она
// покрыта тестами (test_heading.cjs, 9 тестов) — пороги обязаны совпадать.
// Этот код инлайнится в page.evaluate, поэтому живёт строкой.
const TURN_HELPER = `
  const __TURN_START = 0.35, __TURN_STOP = 0.10, __TURN_ONLY = 1.20;
  const __navDecide = (off, allowForward) => {
    const mag = Math.abs(off);
    const wasTurning = !!window.__navTurning;
    const threshold = wasTurning ? __TURN_STOP : __TURN_START;
    if (mag <= threshold) {
      window.__navTurning = false;
      return allowForward === false ? {} : { forward: true };
    }
    window.__navTurning = true;
    const left = off > 0;
    const fwd = (allowForward !== false) && mag <= __TURN_ONLY;
    return left ? { turnLeft: true, forward: fwd }
                : { turnRight: true, forward: fwd };
  };
`;

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
  // handle: факты об исполнении, которые нужны верификаторам Python
  // (например gatherNoTarget: у gather не было ни узла, ни трупа).
  let gatherNoTarget = false;
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
          // анти-рыскание: гистерезис + память поворота (см. TURN_HELPER выше)
          const __TURN_START = 0.35, __TURN_STOP = 0.10, __TURN_ONLY = 1.20;
          const __navDecide = (off, allowForward) => {
            const mag = Math.abs(off);
            const wasTurning = !!window.__navTurning;
            const threshold = wasTurning ? __TURN_STOP : __TURN_START;
            if (mag <= threshold) {
              window.__navTurning = false;
              return allowForward === false ? null : { forward: true };
            }
            window.__navTurning = true;
            const left = off > 0;
            const fwd = (allowForward !== false) && mag <= __TURN_ONLY;
            return left ? { turnLeft: true, forward: fwd }
                        : { turnRight: true, forward: fwd };
          };
          const g = window.__game, sim = g.sim, p = sim.player;
          const e = sim.entities.get(id);
          if (!e || e.dead || (e.hp ?? 0) <= 0) return { gone: true };
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          const desired = Math.atan2(dx, dz);
          let off = desired - p.facing;
          off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
          if (d > 7) {
            // курс на моба одним вызовом face() — без импульсного рыскания
            try { g.controller.face(desired); } catch (_) {}
            g.controller.move({ forward: true });
            return { d, phase: 'chase' };
          }
          // в упор: только доворот, вперёд не идём (иначе толкаем моба).
          // Порог 0.12 рад (FACE_EPS), а не 0.25: при 14° удар мог не попасть.
          if (Math.abs(off) > 0.12) {
            try { g.controller.face(desired); } catch (_) {}
            try { g.controller.stop(); } catch (_) {}
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
    case 4: { // sell: sellAllJunk + surplus materials when bags are crowded
      const sold = await gameClient.evaluate(() => {
        const sim = window.__game.sim;
        let copper0 = 0;
        try { sim.interact(); } catch (_) {}
        try { sim.sellAllJunk && sim.sellAllJunk(); } catch (_) {}
        // Free bag pressure: materials (hides/silk/glands) are common-quality so
        // sellAllJunk skips them; but a FULL bag blocks quest turn-ins
        // (bagsFullError in turnInQuest) and crafting. Sell surplus stacks down
        // to a reserve when the bag is nearly full. Keep food/water/tools.
        const KEEP = { baked_bread: 1, spring_water: 1, conjured_bread: 1, conjured_water: 1, copper_mining_pick: 1 };
        const slots = sim.inventory || [];
        const used = slots.filter(Boolean).length;
        if (used >= 13) {
          const counts = {};
          for (const s of slots) {
            if (!s) continue;
            const id = s.itemId || (s.def && s.def.id);
            counts[id] = (counts[id] || 0) + (s.count || 1);
          }
          for (const id of Object.keys(counts)) {
            if (KEEP[id]) continue;
            if (!/hide|fang|silk|gland|leg|scrap|cloth|weave/i.test(id)) continue; // materials only
            const excess = counts[id] - 5;               // keep a small reserve
            if (excess >= 5) {
              try { sim.sellItem(id, excess); } catch (_) {}
            }
          }
        }
        return true;
      });
      void sold;
      break;
    }
    case 5: { // gather: node first; else harvest a fresh beast/spider corpse
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
        break;
      }
      // 2026-08-23: no node -> corpse-harvest (spider_silk etc. come from
      // componentTagged corpses via sim.harvestCorpse, public on the sim).
      const corpseId = await gameClient.evaluate(() => {
        const g = window.__game, sim = g.sim, p = sim.player;
        let best = null, bd = Infinity;
        for (const e of sim.entities.values()) {
          if (e.kind !== 'mob' || !e.dead) continue;
          const tags = e.componentTags || [];
          if (!tags.length) continue;
          const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z, d = Math.hypot(dx, dz);
          // ПРАВИЛО ИГРЫ (interaction.ts:304): harvestCorpse требует
          // dist <= INTERACT_RANGE = 5 (СЫРАЯ константа, без +2 как у квестов).
          // Раньше здесь стояло 30 — мост находил труп, дёргал harvestCorpse,
          // сервер отвечал 'Too far away.', шаг сгорал впустую.
          if (d <= 5 && d < bd) { bd = d; best = { id: e.id, tags }; }
        }
        return best;
      });
      if (corpseId && corpseId.id != null) {
        await gameClient.evaluate((c) => {
          try { window.__game.sim.harvestCorpse(Number(c.id), c.tags); } catch (_) {}
        }, corpseId);
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
          const hayP = (name + ' ' + id).toLowerCase();
          if (/potion|draught|tonic|elixir|heal/i.test(hayP)) {
            try { sim.useItem(id); return true; } catch (_) { return false; }
          }
        }
        return false;
      });
      if (used) break;
      // No potion: fall back to FOOD (baked_bread / conjured_bread / roasted_*).
      // Eating sits to regen HP in this game (classic food regen); the agent
      // always carries rations, so heal-without-potions is NOT a dead end.
      // Previously this case was a bare no-op -> the death loop at crit HP
      // (30 deaths in run 20152) even though the bag had 13+ food items.
      const ate = await gameClient.evaluate(() => {
        const sim = window.__game.sim;
        const inv = sim.inventory;
        const list = inv instanceof Map ? Array.from(inv.values()) : (Array.isArray(inv) ? inv : []);
        for (const slot of list) {
          if (!slot) continue;
          const def = slot.def || slot.itemDef || {};
          const name = (def.name || '').toLowerCase();
          const id = slot.itemId || def.id;
          if (!id) continue;
          const hayF = (name + ' ' + id).toLowerCase();
          if (/bread|water|roasted|jerky|ration|meal/i.test(hayF)) {
            try { sim.useItem(id); return true; } catch (_) { return false; }
          }
        }
        return false;
      });
      if (!ate) console.warn('[actions] heal: no potion and no food in bag -> honest no-op');
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
    case 9: { // buy: buy cmd.buyItemId (default minor_healing_potion) from a nearby vendor
      const DEFAULT_BUY = 'minor_healing_potion';
      const itemId = (cmd && (cmd.buyItemId || cmd.itemId)) || DEFAULT_BUY;
      const v = await gameClient.evaluate((wanted) => {
        const sim = window.__game.sim, p = sim.player;
        for (const e of sim.entities.values()) {
          if ((e.kind === 'npc' || e.type === 'npc') && (e.vendor || e.isVendor || e.vendorItems)) {
            const dx = e.pos.x - p.pos.x, dz = e.pos.z - p.pos.z;
            if (Math.hypot(dx, dz) <= 12) {
              try { sim.buyItem(e.id, wanted); return e.id; } catch (_) { return null; }
            }
          }
        }
        return null;
      }, itemId);
      if (v == null) console.warn('[actions] buy ' + itemId + ': no vendor in range -> no-op');
      break;
    }
    case 12: { // craft_item: sim.craftItem(recipeId); Craft Cast System runs a cast
      const recipeId = (cmd && cmd.recipeId) || null;
      if (!recipeId) {
        console.warn('[actions] craft_item without recipeId -> no-op');
      } else {
        const res = await gameClient.evaluate((rid) => {
          try { window.__game.sim.craftItem(rid); return { ok: true }; }
          catch (e) { return { ok: false, why: e && e.message }; }
        }, recipeId);
        if (!res || res.ok === false) {
          console.warn('[actions] craft ' + recipeId + ' rejected: ' + (res && res.why));
        } else {
          // Craft Cast System: the craft is an async cast — hold the tab so the
          // cast completes before the next command (result lands in inventory).
          await sleep(2000);
        }
      }
      break;
    }
    case 10: // cast_frostbolt: ranged dmg + 40% slow (mage kit, classes.ts:1585)
    case 11: { // cast_fireball: ranged dmg + DoT (mage kit, classes.ts:1465)
      const abilityId = (idx === 10) ? 'frostbolt' : 'fireball';
      const castRes = await gameClient.evaluate((aid) => {
        const sim = window.__game.sim;
        if (typeof sim.castAbility !== 'function') {
          try { sim.castAbilityBySlot && sim.castAbilityBySlot(-1); } catch (_) {}
          return { ok: false, why: 'no castAbility API' };
        }
        // ensure a hostile target so the cast lands (auto-acquire fallback:
        // nearest attacking mob, casting_lifecycle.ts:771, but pick any nearest
        // hostile when not yet in combat — ranged opening hit)
        try {
          // stop any residual turn/forward input first: a pending turnLeft
          // from a previous chase keeps spinning the camera/facing during the
          // cast (user-visible: "camera rotates while casting fireball").
          try { window.__game.controller.stop(); } catch (_) {}
          if (sim.player.targetId == null) {
            let best = null, bd = Infinity;
            for (const e of sim.entities.values()) {
              if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0) continue;
              if (e.hostile === false) continue;
              const dx = e.pos.x - sim.player.pos.x, dz = e.pos.z - sim.player.pos.z;
              const d = Math.hypot(dx, dz);
              if (d <= 30 && d < bd) { bd = d; best = e; }
            }
            if (best) sim.targetEntity(best.id);
          }
          // 2026-08-24 (замечание пользователя «персонаж должен смотреть на цель
          // чтобы атаковать»): раньше каст шёл БЕЗ доворота — спелл летел в
          // сторону. Теперь перед кастом всегда доворачиваем на текущую цель
          // одним controller.face(). Порог FACE_EPS=0.12 рад (~7°) — см.
          // heading.cjs + test_face_target.cjs (6 тестов).
          try {
            const tgt = sim.entities.get(sim.player.targetId);
            if (tgt && !tgt.dead) {
              const p = sim.player;
              const dx = tgt.pos.x - p.pos.x, dz = tgt.pos.z - p.pos.z;
              const desired = Math.atan2(dx, dz);
              let off = desired - p.facing;
              off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
              if (Math.abs(off) > 0.12) window.__game.controller.face(desired);
            }
          } catch (_) {}
          sim.castAbility(aid);
          return { ok: true };
        } catch (e) {
          return { ok: false, why: e && e.message };
        }
      }, abilityId);
      if (castRes && castRes.ok === false) {
        console.warn('[actions] cast ' + abilityId + ' failed: ' + (castRes.why || '?'));
      }
      // cast time 1.5s: hold the tab so the next command doesn't cancel the cast
      await sleep(1500);
      break;
    }
    default:
      await gameClient.evaluate(() => { try { window.__game.controller.stop(); } catch (_) {} });
  }
  await sleep(gameClient.tickMs);
  return { noTarget: gatherNoTarget };
}

// Walk toward (x,z); returns arrived bool. Geometry (measured live):
// player.facing=0 -> +Z; turnLeft INCREASES facing, turnRight DECREASES it;
// forward moves along (sin(facing), cos(facing)) -> desired = atan2(dx, dz).
// ALWAYS stops the controller on arrive AND on timeout (no inertia running).
//
// STUCK DETECTION (user: "персонаж просто идёт в стену"): if the player has not
// moved for several ticks while we keep pushing forward, the straight line to
// the target is blocked. Turn ~120° and keep walking — a simple wall-slide that
// un-wedges corners/fences without any pathfinding. Progress is measured from
// the position at stuck-check start; two consecutive unstick turns failing to
// produce movement ends the leg honestly (arrived=false, no infinite spin).
async function navigateToCoord(gameClient, x, z, maxSteps) {
  let arrived = false;
  const STUCK_TICKS = 4;        // ~4*220ms of no movement = blocked
  let lastPos = null;
  let stillTicks = 0;
  let unstickAttempts = 0;
  const MAX_UNSTICKS = 6;       // after this, give up this leg
  for (let i = 0; i < (maxSteps || 80); i++) {
    const st = await gameClient.evaluate((tx, tz) => {
      const g = window.__game, p = g.sim.player;
      const dx = tx - p.pos.x, dz = tz - p.pos.z, d = Math.hypot(dx, dz);
      // Анти-рыскание камеры (баг, замеченный пользователем 2026-08-24):
      // единый порог 0.2 рад заставлял агента дёргать камеру влево-вправо
      // каждый тик (курс проскакивал мимо нуля, знак ошибки менялся).
      // Логика и тесты: src/bridge/heading.cjs + test_heading.cjs (9 тестов).
      // Здесь она инлайнится, потому что код исполняется ВНУТРИ страницы,
      // куда require() не дотягивается. Пороги должны совпадать с модулем.
      const __TURN_START = 0.35, __TURN_STOP = 0.10, __TURN_ONLY = 1.20;
      const __navDecide = (off) => {
        const mag = Math.abs(off);
        const wasTurning = !!window.__navTurning;
        const threshold = wasTurning ? __TURN_STOP : __TURN_START;
        if (mag <= threshold) {
          window.__navTurning = false;
          return { forward: true };
        }
        window.__navTurning = true;
        const left = off > 0;
        const fwd = mag <= __TURN_ONLY;
        return left ? { turnLeft: true, forward: fwd }
                    : { turnRight: true, forward: fwd };
      };
      if (d < 5) { try { g.controller.stop(); } catch (_) {} return { arrived: true, d, x: p.pos.x, z: p.pos.z }; }
      // FLEE: in combat at low HP, run AWAY from the nearest hostile instead of
      // toward the target. Leash mechanics drop aggro when far enough; walking
      // on through the mob pack was a death loop (30 deaths in run 20152).
      if (p.inCombat && (p.hp / Math.max(p.maxHp, 1)) < 0.5) {
        let nearest = null, nd = Infinity;
        for (const e of g.sim.entities.values()) {
          if (e.kind !== 'mob' || e.dead || (e.hp ?? 0) <= 0 || e.hostile === false) continue;
          const ex = e.pos.x - p.pos.x, ez = e.pos.z - p.pos.z;
          const ed = Math.hypot(ex, ez);
          if (ed < nd) { nd = ed; nearest = e; }
        }
        if (nearest && nd < 25) {
          // run the OPPOSITE direction from the mob
          const flee = Math.atan2(p.pos.x - nearest.pos.x, p.pos.z - nearest.pos.z);
          try { g.controller.face(flee); } catch (_) {}
          g.controller.move({ forward: true });
          return { arrived: false, d, x: p.pos.x, z: p.pos.z, fleeing: true };
        }
      }
      // 2026-08-24 (зонд подтвердил рыскание 0.347 реверса/сэмпл при импульсном
      // повороте): курс задаём ОДНИМ вызовом controller.face(desired), а не
      // серией turnLeft/turnRight. face() проверен живьём: запрос +1.2 рад дал
      // ровно +1.2 (facing -0.1 -> 1.1). Импульсы поворота порождали
      // автоколебание, потому что доворот проскакивал цель и знак ошибки
      // менялся; при face() камера доводится до курса и стоит.
      const desired = Math.atan2(dx, dz);
      let off = desired - p.facing;
      off = ((off + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
      try { g.controller.face(desired); } catch (_) {}
      // Проактивный хоп: если прошлый тик почти не дал прогресса, а мы на
      // земле — вероятен забор/бордюр впереди. Клик-мышью (main.ts:3959)
      // ставит jump у каждого забора; мы делаем то же по наблюдаемому
      // отсутствию прогресса, т.к. pathCrossesFence в страницу не экспонирован.
      const slow = window.__navLastD !== undefined && (window.__navLastD - d) < 0.25;
      window.__navLastD = d;
      g.controller.move((slow && p.onGround) ? { forward: true, jump: true }
                                            : { forward: true });
      return { arrived: false, d, x: p.pos.x, z: p.pos.z, off: Math.round(off * 100) / 100 };
    }, x, z);
    if (st && st.arrived) { arrived = true; break; }
    // stuck check
    if (lastPos && st) {
      const moved = Math.hypot(st.x - lastPos.x, st.z - lastPos.z);
      if (moved < 0.15) {
        stillTicks++;
        if (stillTicks >= STUCK_TICKS && unstickAttempts < MAX_UNSTICKS) {
          unstickAttempts++;
          // ЛЕСТНИЦА РАСКЛИНИВАНИЯ (исправлено 2026-08-24).
          // КОРНЕВАЯ ПРИЧИНА застревания: забор в этой игре проходится ТОЛЬКО
          // в прыжке — src/sim/player_motion.ts:432
          //   const clearFences = !p.onGround && p.jumping;
          // а наш навигатор слова "jump" не содержал вовсе и сразу
          // разворачивался на 120°, то есть уходил ВДОЛЬ забора, никогда его
          // не преодолевая (пользователь: «упёрся в забор»).
          // Рабочий образец — клик-мышью (src/main.ts:3959-3965): каждый кадр
          // pathCrossesFence(pos, ahead) -> mi.jump = true.
          // Порядок теперь: СНАЧАЛА 2 попытки перепрыгнуть по курсу, и только
          // если забор непреодолим — старый обход поворотом.
          if (unstickAttempts <= 2) {
            const hop = await gameClient.evaluate(() => {
              const g = window.__game, p = g.sim.player;
              // прыжок работает только с земли (player_motion.ts:637:
              // inp.jump && (p.onGround || coyote))
              if (!p.onGround) return { skipped: 'airborne' };
              try {
                g.controller.move({ forward: true, jump: true });
              } catch (_) { return { skipped: 'move-failed' }; }
              return { jumped: true, y: +p.pos.y.toFixed(2) };
            });
            void hop;
            // держим прыжок на протяжении дуги: клиренс действует всю дугу
            await sleep(gameClient.tickMs * 3);
            stillTicks = 0;
            continue;
          }
          // turn off-axis and push through: alternate left/right so repeated
          // wedges zigzag out instead of grinding one wall
          const dirSign = (unstickAttempts % 2 === 1) ? 1 : -1;
          const deg120 = dirSign * (Math.PI * 2 / 3);
          await gameClient.evaluate((delta) => {
            const g = window.__game, p = g.sim.player;
            try { g.controller.stop(); } catch (_) {}
            let remaining = delta;
            // face() rotates instantly when available; otherwise tick-turns
            if (typeof g.controller.face === 'function') {
              try { g.controller.face(p.facing + remaining); } catch (_) {}
              remaining = 0;
            }
            if (remaining !== 0) {
              let t = 0;
              const iv = setInterval(() => {
                try { g.controller.move({ turnLeft: remaining > 0 }); } catch (_) {}
                if (++t >= 4) { clearInterval(iv); try { g.controller.move({ forward: true }); } catch (_) {} }
              }, 60);
            }
          }, deg120);
          await sleep(gameClient.tickMs);
          stillTicks = 0;
          lastPos = null;
          continue;
        }
        if (unstickAttempts >= MAX_UNSTICKS) break; // honest give-up
      } else {
        stillTicks = 0;
      }
    }
    if (st) lastPos = { x: st.x, z: st.z };
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
  // 2026-08-24: раньше здесь стоял поворот каждый 7-й шаг (i % 7 === 6) и
  // controller.stop() на КАЖДОМ тике. Это давало ровно то, что видел
  // пользователь: агент идёт и постоянно вертит камерой, а из-за stop() ещё и
  // теряет разгон. Теперь: один поворот в НАЧАЛЕ отрезка (выбираем новый курс),
  // затем идём прямо, не трогая камеру и не сбрасывая ввод каждый тик.
  const total = steps || 10;
  // курс выбирается ОДИН раз на отрезок: короткий доворот, дальше только forward
  await gameClient.evaluate(() => {
    try { window.__game.controller.stop(); } catch (_) {}
    try {
      // один новый курс на весь отрезок через face() — камера не дрожит
      const p = window.__game.sim.player;
      const newFacing = p.facing + (Math.random() * 2 - 1) * 1.2;
      window.__game.controller.face(newFacing);
    } catch (_) {}
  });
  await sleep(gameClient.tickMs);
  await gameClient.evaluate(() => {
    try { window.__game.controller.move({ forward: true }); } catch (_) {}
  });
  for (let i = 1; i < total; i++) {
    // НЕ переотправляем команду каждый тик: ввод контроллера персистентный,
    // повторный move() с тем же значением только мешает (и раньше здесь был
    // stop(), который рвал движение).
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
    const applied = await apply(cmd.idx || 0, cmd);
    const r = await buildSnapshot(gameClient);
    if (r == null) return { ok: false, error: 'snapshot after step failed' };
    const out = { ok: true, info: r };
    // Факты исполнения для Python-верификаторов (2026-08-24): noTarget=true
    // означает, что у скилла не было объекта действия (нет узла/трупа для
    // gather) — верификатор превращает это в честный failure, а не в
    // inconclusive, иначе агент бьёт в пустоту без обучающего сигнала.
    if (applied && applied.noTarget) out.noTarget = true;
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
