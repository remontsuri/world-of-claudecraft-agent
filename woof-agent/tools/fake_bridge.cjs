#!/usr/bin/env node
/*
 * fake_bridge.cjs - полигон моста (:8791) без браузера и без игры.
 *
 * Отвечает тем же контрактом, что browser_bridge.cjs, и ГЛАВНОЕ: пишет
 * "violations" - нарушения протокола со стороны агента. Смысл полигона в том,
 * что заглушка вызывала молчание как успех: шаг навыка без idx, raw_move без
 * kind, взаимодействие с NPC вне радиуса проходили "нормально". Здесь они
 * фиксируются как нарушения, а не как успех.
 *
 * Мир: NPC lin(12,-4) даёт q_spiders (убить 3 spiderling), затем сдать до 3.
 * Запуск: node tools/fake_bridge.cjs [port]     (default 8791)
 */
const http = require('http');

const PORT = Number(process.argv[2] || process.env.FAKE_PORT || 8791);
const TRACE = process.env.FAKE_TRACE === '1';
const INTERACT = 5.0;      // радиус взаимодействия в игре
const ATTACK = 7.0;        // радиус атаки
const SPEED = 8.0;         // юнитов за один шаг navigate

const NPC = { id: 'npc_lin', kind: 'npc', templateId: 'apothecary_lin', name: 'Lin', x: 12, z: -4 };
const QUEST = { id: 'q_spiders', name: 'Spiders', required: 3, targetMobId: 'spiderling' };

const world = {
  player: { hp: 138, maxHp: 138, x: 0, z: 0, facing: 0, level: 1, dead: false, in_combat: false },
  mobs: [], kills: 0, deaths: 0, questsDone: 0,
  quest: { state: 'none', progress: 0, killCount: 0 },
  cadenceBlocked: [],
};
let idSeq = 1;
const violations = [];
const cooldowns = new Map();      // idx -> тиков перезарядки (как в actions.cjs)

function spawnMobs(n) {
  for (let i = 0; i < n; i++) {
    const ang = (i / n) * Math.PI * 2;
    world.mobs.push({
      id: 'mob_' + (idSeq++), kind: 'mob', type: 'spiderling', templateId: 'spiderling',
      name: 'Spiderling', hostile: true, dead: false, hp: 20,
      x: 22 + Math.cos(ang) * 4, z: 10 + Math.sin(ang) * 4,
    });
  }
}
spawnMobs(6);

function dist(e) { const dx = e.x - world.player.x, dz = e.z - world.player.z; return Math.hypot(dx, dz); }
function liveMobs() { return world.mobs.filter(m => !m.dead); }
function corpseLootable() { return world.mobs.find(m => m.dead && !m.looted); }
function questActive() { return world.quest.state === 'active'; }
function questReady() { return world.quest.state === 'active' && world.quest.progress >= QUEST.required; }

function nearby() {
  const out = [];
  const npc = Object.assign({}, NPC, {
    dist: dist(NPC),
    canQuest: !questActive() && !questReady() && world.quest.state !== 'done',
    vendor: true,
  });
  out.push(npc);
  for (const m of world.mobs) {
    const e = {
      id: m.id, kind: 'mob', templateId: m.type, name: m.name, x: m.x, z: m.z,
      hostile: true, dead: m.dead, dist: dist(m), hp: m.hp,
      lootable: m.dead && !m.looted, looted: !!m.looted,
      quest_target: questActive() && m.type === QUEST.targetMobId,
    };
    if (e.dist <= 90) out.push(e);
  }
  return out;
}

function questsBlock() {
  const q = {
    id: QUEST.id, name: QUEST.name, progress: world.quest.progress, required: QUEST.required,
    killCount: world.quest.killCount, targetMobId: QUEST.targetMobId,
    giverId: NPC.id, giverName: NPC.name,
    turnInNpc: { x: NPC.x, z: NPC.z, name: NPC.name },
  };
  if (questActive() && !questReady()) return { active: [Object.assign({ state: 'active' }, q)], ready: [], done: [] };
  if (questReady()) return { active: [], ready: [Object.assign({ state: 'ready' }, q)], done: [] };
  if (world.quest.state === 'done') return { active: [], ready: [], done: [Object.assign({ state: 'done' }, q)] };
  return { active: [], ready: [], done: [] };
}

function snapshot() {
  const active = questsBlock().active[0];
  const ready = questsBlock().ready[0];
  return {
    player: Object.assign({}, world.player, { in_combat: world.player.in_combat }),
    player_pos: [world.player.x, world.player.z],
    nearby: nearby(),
    quests: questsBlock(),
    kills: world.kills, deaths: world.deaths, quests_done: world.questsDone,
    quest_cadence_blocked: world.cadenceBlocked,
    npc_positions: { [NPC.id]: [NPC.x, NPC.z], apothecary_lin: [NPC.x, NPC.z], lin: [NPC.x, NPC.z] },
    in_combat: world.player.in_combat,
    player_class: 'warrior',
    level: world.player.level, xp: 0, copper: 0, mana: 0, maxMana: 0,
    active_quest_id: active ? active.id : (ready ? ready.id : null),
  };
}

function violation(kind, detail) {
  violations.push({ at: Date.now(), kind, detail });
  if (TRACE) console.log('VIOLATION ' + kind + ': ' + detail);
}

function handleStep(cmd) {
  // Контракт моста: step обязан нести idx, иначе это не шаг навыка
  if (typeof cmd.idx !== 'number') {
    violation('step_without_idx', JSON.stringify(cmd));
    return { ok: false, error: 'step requires numeric idx' };
  }
  const idx = cmd.idx;
  if (idx < 0 || idx > 12) {
    violation('idx_out_of_range', 'idx=' + idx);
    return { ok: false, error: 'idx out of range: ' + idx };
  }
  switch (idx) {
    case 0: {                                   // farm
      const target = cmd.mobId
        ? world.mobs.find(m => m.id === cmd.mobId)
        : liveMobs().sort((a, b) => dist(a) - dist(b))[0];
      if (!target || target.dead) return { ok: false, error: 'no target' };
      if (dist(target) > ATTACK) {
        violation('attack_out_of_range', target.id + ' dist=' + dist(target).toFixed(1));
        return { ok: false, error: 'target out of attack range' };
      }
      target.hp -= 999; target.dead = true;
      if (target.type === QUEST.targetMobId && questActive()) {
        world.quest.progress = Math.min(QUEST.required, world.quest.progress + 1);
        world.quest.killCount++;
      }
      world.kills++;
      return { ok: true, killed: true, info: snapshot() };
    }
    case 1: {                                   // loot
      const corpse = cmd.mobId ? world.mobs.find(m => m.id === cmd.mobId) : corpseLootable();
      if (!corpse || !corpse.dead) return { ok: false, error: 'no corpse' };
      if (dist(corpse) > INTERACT) {
        violation('loot_out_of_range', corpse.id + ' dist=' + dist(corpse).toFixed(1));
        return { ok: false, error: 'corpse out of interact range' };
      }
      corpse.looted = true;
      return { ok: true, looted: true, info: snapshot() };
    }
    case 2: {                                   // accept_quest
      if (dist(NPC) > INTERACT) {
        violation('accept_out_of_range', 'dist=' + dist(NPC).toFixed(1));
        return { ok: false, error: 'npc out of interact range' };
      }
      if (questActive() || world.quest.state === 'done') {
        violation('accept_while_active', 'state=' + world.quest.state);
        return { ok: false, error: 'quest already taken' };
      }
      world.quest.state = 'active'; world.quest.progress = 0; world.quest.killCount = 0;
      return { ok: true, accepted: true, info: snapshot() };
    }
    case 3: {                                   // turn_in_quest
      if (!questReady()) return { ok: false, error: 'no ready quest' };
      if (dist(NPC) > INTERACT) {
        violation('turn_in_out_of_range', 'dist=' + dist(NPC).toFixed(1));
        return { ok: false, error: 'npc out of interact range' };
      }
      world.quest.state = 'done'; world.questsDone++;
      world.player.level = 2;
      return { ok: true, turned_in: true, info: snapshot() };
    }
    case 4: case 5: case 6: case 8: case 9: case 10: case 11: case 12:
      return { ok: true, info: snapshot() };
    case 7: {                                   // heal
      if (world.player.hp >= world.player.maxHp) return { ok: false, error: 'already full hp' };
      world.player.hp = world.player.maxHp;
      return { ok: true, info: snapshot() };
    }
    default:
      violation('unknown_idx', 'idx=' + idx);
      return { ok: false, error: 'unknown skill idx ' + idx };
  }
}

function handleNavigate(cmd) {
  const tx = Number(cmd.x), tz = Number(cmd.z);
  const maxSteps = Number(cmd.max_steps || 80);
  if (!Number.isFinite(tx) || !Number.isFinite(tz)) {
    violation('navigate_without_target', JSON.stringify(cmd));
    return { ok: false, error: 'navigate requires numeric x/z' };
  }
  let steps = 0;
  while (steps < maxSteps) {
    const dx = tx - world.player.x, dz = tz - world.player.z;
    const d = Math.hypot(dx, dz);
    if (d <= 0.5) break;
    const k = Math.min(1, SPEED / d);
    world.player.x += dx * k; world.player.z += dz * k;
    steps++;
  }
  const left = Math.hypot(tx - world.player.x, tz - world.player.z);
  return { ok: true, arrived: left <= 0.5, info: snapshot() };
}

function handleRawMove(cmd) {
  // Контракт: raw_move несёт kind (forward|back|turnLeft|turnRight)
  const kind = cmd.kind;
  if (typeof kind !== 'string') {
    violation('raw_move_without_kind', JSON.stringify(cmd));
    return { ok: false, error: 'raw_move requires kind' };
  }
  if (!['forward', 'back', 'turnLeft', 'turnRight'].includes(kind)) {
    violation('raw_move_bad_kind', kind);
    return { ok: false, error: 'unknown kind: ' + kind };
  }
  const step = kind === 'back' ? -3 : 3;
  if (kind === 'forward') { world.player.x += Math.cos(world.player.facing) * step; world.player.z += Math.sin(world.player.facing) * step; }
  if (kind === 'back') { world.player.x -= Math.cos(world.player.facing) * step; world.player.z -= Math.sin(world.player.facing) * step; }
  if (kind === 'turnLeft') world.player.facing += 1.0;
  if (kind === 'turnRight') world.player.facing -= 1.0;
  return { ok: true, info: snapshot() };
}

function handleExplore(cmd) {
  const steps = Number(cmd.steps || 10);
  world.player.x += Math.cos(world.player.facing) * 2 * steps;
  world.player.z += Math.sin(world.player.facing) * 2 * steps;
  return { ok: true, arrived: true, info: snapshot() };
}

function dispatch(cmd) {
  switch (cmd.action) {
    case 'snapshot': return { ok: true, info: snapshot() };
    case 'step':     return handleStep(cmd);
    case 'navigate': return handleNavigate(cmd);
    case 'raw_move': return handleRawMove(cmd);
    case 'explore':  return handleExplore(cmd);
    case 'respawn':
      world.player.dead = false; world.player.hp = world.player.maxHp;
      world.player.x = 0; world.player.z = 0; world.deaths++;
      return { ok: true, info: snapshot() };
    case 'health':
      return { ok: true, bridge: true, page: true, game: true, fake: true };
    default:
      violation('unknown_action', String(cmd.action));
      return { ok: false, error: 'unknown action: ' + cmd.action };
  }
}

const server = http.createServer((req, res) => {
  const send = (code, obj) => {
    const body = JSON.stringify(obj);
    res.writeHead(code, { 'content-type': 'application/json' });
    res.end(body);
  };
  if (req.method === 'GET' && req.url === '/violations') {
    return send(200, { ok: true, violations, count: violations.length });
  }
  if (req.method === 'GET' && req.url === '/reset') {
    world.player = { hp: 138, maxHp: 138, x: 0, z: 0, facing: 0, level: 1, dead: false, in_combat: false };
    world.kills = 0; world.deaths = 0; world.questsDone = 0;
    world.quest = { state: 'none', progress: 0, killCount: 0 };
    world.mobs = []; cooldowns.clear();
    spawnMobs(6);
    return send(200, { ok: true, reset: true });
  }
  let raw = '';
  req.on('data', c => raw += c);
  req.on('end', () => {
    let cmd = {};
    try { cmd = raw ? JSON.parse(raw) : {}; } catch (e) { return send(200, { ok: false, error: 'bad json' }); }
    const t0 = Date.now();
    const resp = dispatch(cmd);
    if (TRACE) {
      console.log(JSON.stringify(cmd) + ' -> ok=' + resp.ok + ' (' + (Date.now() - t0) + 'ms)');
    }
    send(200, resp);
  });
});

server.listen(PORT, '127.0.0.1', () => {
  console.log('[fake_bridge] listening on :' + PORT + '  (violations: GET /violations, reset: GET /reset)');
});
