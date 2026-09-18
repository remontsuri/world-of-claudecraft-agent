// Какие типы целей квестов вообще есть в игре и какие из них проходимы нашим action space.
import { QUESTS, QUEST_ORDER } from '../game/src/sim/data';
const byType = new Map<string, number>();
const fields = new Map<string, number>();
const examples = new Map<string, string>();
for (const qid of QUEST_ORDER) {
  const q = (QUESTS as any)[qid];
  for (const o of q?.objectives ?? []) {
    byType.set(o.type, (byType.get(o.type) ?? 0) + 1);
    if (!examples.has(o.type)) examples.set(o.type, `${qid}: ${JSON.stringify(o)}`);
    for (const k of Object.keys(o)) fields.set(k, (fields.get(k) ?? 0) + 1);
  }
}
console.log('типы целей (всего квестов ' + QUEST_ORDER.length + '):');
for (const [t, n] of [...byType.entries()].sort((a, b) => b[1] - a[1])) console.log(`  ${t}: ${n}   пример: ${examples.get(t)}`);
console.log('\nполя целей:', [...fields.entries()].sort((a,b)=>b[1]-a[1]).map(([k,n])=>`${k}(${n})`).join(', '));
// первые 8 квестов стартовой зоны: что реально может взять воин 1 уровня
console.log('\nпервые 12 квестов QUEST_ORDER:');
for (const qid of QUEST_ORDER.slice(0, 12)) {
  const q = (QUESTS as any)[qid];
  console.log(`  ${qid}: "${q.name}" giver=${q.giverNpcId} turnIn=${q.turnInNpcId} reqClass=${q.requiredClass ?? '-'} requiresQuest=${q.requiresQuest ?? '-'} obj=${JSON.stringify(q.objectives)}`);
}
