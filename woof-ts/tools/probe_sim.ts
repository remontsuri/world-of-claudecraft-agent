// Зонд: фактическая форма Sim/Entity/квестов (первоисточник — runtime, не догадки).
import { Sim } from '../game/src/sim/sim';
import { allocateHeadlessGathererIdentity } from '../game/headless/gatherer_identity';
import { ACTIONS, NUM_ACTIONS, obsSize } from '../game/src/sim/obs';
import { QUEST_ORDER, QUESTS, CLASSES } from '../game/src/sim/data';
import { MAX_LEVEL, MELEE_RANGE, INTERACT_RANGE } from '../game/src/sim/types';

const sim: any = new (Sim as any)({
  seed: 42, playerClass: 'warrior', respawnSeconds: 15, autoEquip: true,
  idleMobTickRadius: 80, gathererIdentity: allocateHeadlessGathererIdentity(),
});
const out: any = {};
out.facts = { obsSize: obsSize(), NUM_ACTIONS, MAX_LEVEL, MELEE_RANGE, INTERACT_RANGE,
              quests: QUEST_ORDER.length, classes: Object.keys(CLASSES) };
out.simMethods = Object.getOwnPropertyNames(Object.getPrototypeOf(sim)).filter((n) => typeof sim[n] === 'function').sort();
out.simFields = Object.keys(sim).sort();
out.counters = sim.counters;
out.player = Object.fromEntries(Object.keys(sim.player).map((k) => {
  const v = sim.player[k];
  return [k, (v && typeof v === 'object') ? `<${Array.isArray(v) ? 'array' : 'obj'}:${Object.keys(v).slice(0,8).join(',')}>` : v];
}));
const ents = [...sim.entities.values()];
out.entityCount = ents.length;
const byKind: any = {};
for (const e of ents) { (byKind[e.kind] ??= []).push(e); }
out.kinds = Object.fromEntries(Object.entries(byKind).map(([k, v]: any) => [k, v.length]));
const sample = (e: any) => e ? Object.fromEntries(['id','kind','type','templateId','name','level','hp','maxHp','hostile','dead','lootable','questIds','aggroTargetId'].map((k) => [k, e[k]]).concat([['pos', e.pos && {x:+e.pos.x.toFixed(1), z:+e.pos.z.toFixed(1)}]])) : null;
out.sampleMob = sample(byKind.mob?.[0]);
out.sampleNpc = sample(byKind.npc?.[0]);
out.npcsWithQuests = (byKind.npc ?? []).filter((n: any) => (n.questIds ?? []).length > 0).slice(0, 6).map((n: any) => ({ id: n.id, name: n.name, type: n.type, questIds: n.questIds, pos: { x: +n.pos.x.toFixed(1), z: +n.pos.z.toFixed(1) } }));
out.playerPos = { x: +sim.player.pos.x.toFixed(1), z: +sim.player.pos.z.toFixed(1) };
out.questStateApi = { q_wolves: sim.questState?.('q_wolves'), logSize: sim.questLog?.size ?? null,
  logSample: sim.questLog ? [...sim.questLog.entries()].slice(0,3) : null };
out.questDef = QUESTS['q_wolves'] ? { id: QUESTS['q_wolves'].id, name: QUESTS['q_wolves'].name, giver: QUESTS['q_wolves'].giverId ?? QUESTS['q_wolves'].giver ?? null, keys: Object.keys(QUESTS['q_wolves']), objectives: QUESTS['q_wolves'].objectives } : null;
out.warriorAbilities = CLASSES.warrior.abilities.map((a: any) => a.id ?? a).slice(0, 12);
out.inventory = (sim.inventory ?? []).slice(0, 5);
console.log(JSON.stringify(out, null, 1));
