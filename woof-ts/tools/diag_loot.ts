// Почему LOOT_FAILED: что игра даёт прочитать про лут/инвентарь/ошибки.
import { Sim } from '../game/src/sim/sim';
const sim: any = new Sim({ seed: 42, playerClass: 'warrior', playerLevel: 3, autoEquip: true });
const keys = Object.keys(sim).filter(k => /inv|bag|item|error|toast|log|loot|corpse/i.test(k));
console.log('поля Sim про инвентарь/ошибки/лут:', keys.join(', '));
const proto = Object.getOwnPropertyNames(Object.getPrototypeOf(sim)).filter(m => /inv|bag|item|error|toast|loot|corpse/i.test(m));
console.log('методы Sim:', proto.join(', '));
const p: any = sim.player;
console.log('поля player:', Object.keys(p).filter(k => /inv|bag|item|error|toast|loot/i.test(k)).join(', '));
console.log('весь список полей player (первые 40):', Object.keys(p).slice(0, 40).join(', '));
// есть ли журнал ошибок/тостов
for (const k of ['errors', 'toasts', 'messages', 'log', 'errorLog', 'lastError']) {
  if (sim[k] !== undefined) console.log(`sim.${k} =`, JSON.stringify(sim[k]).slice(0, 200));
  if (p[k] !== undefined) console.log(`player.${k} =`, JSON.stringify(p[k]).slice(0, 200));
}
