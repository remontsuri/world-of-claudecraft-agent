// dump_quest_oracle.ts — генерит data/quest_oracle.json из самого игрового кода.
//
// Зачем: obs отдаёт по каждому из 224 квестов только (state, progress), а где
// стоит цель — не отдаёт. Координаты берём у игры, а не парсим глазами:
// questObjectiveAreas() из src/sim/quest_targets.ts раскладывает цели по
// мировым координатам из статических таблиц (MOBS/CAMPS/GROUND_OBJECTS/NPCS),
// без интерет-радиуса и без состояния Sim.
//
// Запуск (в клоне levy-street/world-of-claudecraft, нужен только src/sim):
//   npx --yes esbuild dump_quest_oracle.ts --bundle --platform=node \
//       --format=cjs --outfile=/tmp/dump.cjs && node /tmp/dump.cjs > data/quest_oracle.json
//
// Формат: {"order": [...224 id в порядке obs...], "obs_base": 156, "quests": {...}}

import { QUEST_ORDER, QUESTS, NPCS } from './src/sim/data';
import { ACTIONS, obsSize } from './src/sim/obs';
import { questObjectiveAreas } from './src/sim/quest_targets';

const log = new Map<string, any>();
for (const qid of QUEST_ORDER) {
  const q = (QUESTS as any)[qid];
  if (!q) continue;
  log.set(qid, { questId: qid, counts: q.objectives.map(() => 0), state: 'active' });
}
const areas: any[] = questObjectiveAreas(log as any);
const areaFor = new Map<string, any>();
for (const a of areas) for (const o of a.objectives) areaFor.set(`${o.questId}#${o.objectiveIndex}`, a);

const npcPos = (id: string | undefined) => {
  if (!id) return null;
  const n = (NPCS as any)[id];
  return n && n.pos ? { x: n.pos.x, z: n.pos.z } : null;
};

const quests: Record<string, any> = {};
for (const qid of QUEST_ORDER) {
  const q = (QUESTS as any)[qid];
  if (!q) continue;
  quests[qid] = {
    name: q.name ?? null,
    giver: npcPos(q.giverNpcId),
    turnIn: npcPos(q.turnInNpcId),
    requires: q.requiresQuest ?? null,
    xp: q.xpReward ?? null,
    copper: q.copperReward ?? null,
    objectives: (q.objectives as any[]).map((o, i) => {
      const a = areaFor.get(`${qid}#${i}`);
      return {
        type: o.type,
        count: o.count ?? null,
        targetMobId: o.targetMobId ?? null, itemId: o.itemId ?? null,
        targetNpcId: o.targetNpcId ?? null, campId: o.campId ?? null,
        area: a ? { x: a.center.x, z: a.center.z, r: a.radius } : null,
      };
    }),
  };
}
// Метаданные версии: по ним quest_oracle.py понимает, подходит ли таблица сборке.
// Слоты способностей берём из списка действий (13 + ABILITY_SLOTS) — это не
// зависит от того, где в данной версии определён CLASSES.
const abilitySlots = ACTIONS.filter((a) => a.startsWith('ability_')).length;
console.log(JSON.stringify({
  game: { quests_count: QUEST_ORDER.length, obs_size: obsSize(), actions: ACTIONS.length,
          ability_slots: abilitySlots, base_actions: ACTIONS.filter((a) => !a.startsWith('ability_')).length },
  order: [...QUEST_ORDER], quests,
}));
