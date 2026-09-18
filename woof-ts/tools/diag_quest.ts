// Диагностика: почему второй квест у того же NPC не принимается.
import { AgentCore } from '../src/core/agent';
import { ArbitrationLayer } from '../src/decision/arbitration';
import { GoalFSM } from '../src/decision/fsm';
import { SkillLibrary, WorldMemory } from '../src/memory/memory';
import { HEADLESS_UNSUPPORTED } from '../src/skills/canon';
import { SkillExecutor } from '../src/skills/executor';
import { SimWorld } from '../src/world/sim_world';
import { QUESTS } from '../game/src/sim/data';

const world = SimWorld.create({ seed: 42, playerClass: 'warrior', frameSkip: 5, maxSteps: 0, gathererIdentity: { kind: 'headless', id: 'hl:diag:3' } });
const memory = new WorldMemory(), library = new SkillLibrary(), fsm = new GoalFSM();
const ranges = { meleeRange: world.facts.meleeRange, interactRange: world.facts.interactRange };
const arb = new ArbitrationLayer(fsm, memory, ranges, world.capabilities);
for (const s of Object.keys(HEADLESS_UNSUPPORTED)) arb.disable(s);
const agent = new AgentCore(world, fsm, arb, new SkillExecutor(world, memory, ranges), memory, library, { quiet: true, verbose: false });
agent.run(15);
const sim = world.debugSim();
const m = world.observe();
console.log(`после 15 решений: phase=${fsm.phase} quests_done=${m.counters.questsDone ?? m.counters.questsCompleted} kills=${m.counters.kills} pos=(${m.player.x.toFixed(1)},${m.player.z.toFixed(1)})`);
console.log('журнал квестов:', [...sim.questLog.values()].map((qp: any) => `${qp.questId}:${qp.state}:${JSON.stringify(qp.counts)}`).join(' | ') || '(пуст)');
const npcs = m.npcs.filter((n) => n.questIds.length > 0);
for (const n of npcs) {
  console.log(`\nNPC ${n.templateId} "${n.name}" d=${n.dist.toFixed(1)} questIds=[${n.questIds.join(',')}]`);
  for (const qid of n.questIds) {
    const def = (QUESTS as any)[qid];
    console.log(`   ${qid}: state=${sim.questState(qid)} name="${def?.name}" giver=${def?.giverNpcId} turnIn=${def?.turnInNpcId} completionEffect=${!!def?.completionEffect} minLevel=${def?.minLevel ?? '-'} classes=${def?.classes ? JSON.stringify(def.classes) : '-'} prereq=${def?.prerequisiteQuestId ?? def?.requiresQuest ?? '-'} keys=${Object.keys(def ?? {}).join(',')}`);
  }
}
console.log('\naccept ещё раз:');
const before = [...sim.questLog.values()].map((qp: any) => qp.questId).join(',');
world.stepAction('interact');
const m2 = world.observe();
console.log('  журнал до:', before || '(пуст)');
console.log('  журнал после:', [...sim.questLog.values()].map((qp: any) => `${qp.questId}:${qp.state}`).join(',') || '(пуст)');
console.log('  ошибки мира (последние):', JSON.stringify((sim.errors ?? sim.lastErrors ?? []).slice?.(-3) ?? 'нет поля'));
