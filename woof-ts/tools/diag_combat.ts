// Зонд боя: почему farm не наносит урона. Факты из мира, без догадок.
import { SimWorld } from '../src/world/sim_world';
import { QUESTS } from '../game/src/sim/data';

const w = SimWorld.create({ seed: 42, playerClass: 'warrior', frameSkip: 5, gathererIdentity: { kind: 'headless', id: 'hl:diag:1' } });
let m = w.observe();
const fmt = (e: any) => `${e.kind}/${e.templateId}"${e.name}" hp=${e.hp}/${e.maxHp} lvl=${e.level} hostile=${e.hostile} dead=${e.dead} loot=${e.lootable} d=${e.dist.toFixed(1)} brg=${e.bearing.toFixed(2)} q=[${e.questIds.join(',')}]`;
console.log('игрок:', `pos=(${m.player.x.toFixed(1)},${m.player.z.toFixed(1)}) facing=${m.player.facing.toFixed(2)} hp=${m.player.hp}/${m.player.maxHp}`);
console.log('сущности в радиусе 60:');
for (const e of [...m.nearby, ...m.npcs, ...m.corpses].sort((a, b) => a.dist - b.dist).slice(0, 12)) console.log('  ', fmt(e));
console.log('квесты в журнале:', m.quests.map((q) => `${q.id}:${q.state}:${q.progress}/${q.required}:${JSON.stringify(q.objectives)}`).join(' | '));
const qdef = (QUESTS as any)['q_hub_know_your_numbers'];
console.log('q_hub_know_your_numbers из игры:', JSON.stringify({ name: qdef?.name, giver: qdef?.giverNpcId, turnIn: qdef?.turnInNpcId, objectives: qdef?.objectives }));

console.log('\n--- target_nearest ---');
w.stepAction('target_nearest');
m = w.observe();
const sim = w.debugSim();
console.log('targetId =', sim.player.targetId, '| target в модели:', m.target ? fmt(m.target) : 'НЕТ');
console.log('facing =', sim.player.facing.toFixed(3), '| autoAttack =', sim.player.autoAttack, '| inCombat =', sim.player.inCombat, '| gcd =', (sim.player.gcdRemaining ?? 0).toFixed(2));

console.log('\n--- attack + 10 шагов (50 тиков) ---');
w.stepAction('attack');
for (let i = 0; i < 10; i++) {
  const r = w.stepAction('attack');
  const mm = w.observe();
  const t = mm.target;
  console.log(
    `step=${r.step} tgt=${t ? `${t.templateId} hp=${t.hp}/${t.maxHp} d=${t.dist.toFixed(1)} brg=${t.bearing.toFixed(2)}` : 'НЕТ'}` +
    ` dmg=${r.counters.damageDealt} kills=${r.counters.kills} face=${mm.player.facing.toFixed(2)} aa=${mm.player.autoAttack} gcd=${(sim.player.gcdRemaining ?? 0).toFixed(2)} pos=(${mm.player.x.toFixed(1)},${mm.player.z.toFixed(1)})`,
  );
}
console.log('\n--- доворот на цель и ещё 10 шагов ---');
for (let i = 0; i < 10; i++) {
  const mm = w.observe();
  const t = mm.target;
  if (!t) { console.log('цели нет'); break; }
  const act = Math.abs(t.bearing) > 0.2 ? (t.bearing > 0 ? 'turn_left' : 'turn_right') : 'attack';
  const r = w.stepAction(act);
  console.log(`step=${r.step} act=${act} tgt hp=${t.hp}/${t.maxHp} d=${t.dist.toFixed(1)} brg=${t.bearing.toFixed(2)} dmg=${r.counters.damageDealt} kills=${r.counters.kills}`);
}
