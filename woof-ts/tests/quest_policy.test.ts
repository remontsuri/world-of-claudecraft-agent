// Политика квестов: заявленные правила принятия/приоритета обязаны совпадать с
// данными игры. Правила объявлены в PROGRESS/README и проверяются здесь, чтобы
// «агент берёт квест» не зависело от того, что кто-то переписал порог в коде.
import { describe, expect, it } from 'vitest';

import { questDef, questOrder } from '../src/facts';
import {
  SUPPORTED_OBJECTIVE_TYPES,
  UNSUPPORTED_OBJECTIVE_TYPES,
  canFightMob,
  incompletableReasons,
  isQuestCompletable,
  objectiveTypeCounts,
  predictedAccept,
  questPriority,
} from '../src/world/quest_policy';
import { npcPins } from '../src/facts';

const typesOf = (qid: string): string[] =>
  (questDef(qid)?.objectives ?? []).map((o: { type: string }) => o.type);

const findQuest = (pred: (types: string[]) => boolean): string | undefined =>
  questOrder.find((qid) => pred(typesOf(qid)));

describe('что агент вообще может пройти', () => {
  it('поддерживаемые типы целей — kill/collect/interact, остальные заявлены как CUT с причиной', () => {
    expect([...SUPPORTED_OBJECTIVE_TYPES].sort()).toEqual(['collect', 'interact', 'kill']);
    expect(Object.keys(UNSUPPORTED_OBJECTIVE_TYPES).length).toBeGreaterThan(0);
    for (const [t, why] of Object.entries(UNSUPPORTED_OBJECTIVE_TYPES)) {
      expect(why.length).toBeGreaterThan(10);
      expect(SUPPORTED_OBJECTIVE_TYPES).not.toContain(t as (typeof SUPPORTED_OBJECTIVE_TYPES)[number]);
    }
  });

  it('счётчики типов целей покрывают все квесты игры', () => {
    const counts = objectiveTypeCounts();
    expect(counts.kill).toBeGreaterThan(0);
    expect(Object.values(counts).reduce((a, b) => a + b, 0)).toBeGreaterThan(100);
  });

  it('квест только с kill/collect/interact проходим; с escort/gather/farm — нет, и причина названа', () => {
    const killOnly = findQuest((t) => t.length > 0 && t.every((x) => x === 'kill'));
    expect(killOnly).toBeDefined();
    expect(isQuestCompletable(killOnly!)).toBe(true);
    expect(incompletableReasons(killOnly!)).toEqual([]);

    const unsupported = findQuest((t) => t.some((x) => !SUPPORTED_OBJECTIVE_TYPES.includes(x as never)));
    if (unsupported) {
      expect(isQuestCompletable(unsupported)).toBe(false);
      expect(incompletableReasons(unsupported).length).toBeGreaterThan(0);
    }
  });
});

describe('приоритет квестов', () => {
  it('kill-only раньше смешанных, смешанные раньше interact, interact раньше collect-only', () => {
    const killOnly = findQuest((t) => t.length > 0 && t.every((x) => x === 'kill'))!;
    const mixed = findQuest((t) => t.includes('kill') && (t.includes('collect') || t.includes('interact')));
    const collectOnly = findQuest((t) => t.length > 0 && t.every((x) => x === 'collect'));

    expect(questPriority(killOnly)).toBe(0);
    if (mixed) expect(questPriority(mixed)).toBe(1);
    if (collectOnly) expect(questPriority(collectOnly)).toBe(3);
    // Квест неизвестного/пустого типа — последний, но не NaN.
    expect(questPriority('нет_такого_квеста')).toBe(4);
  });
});

describe('правило игры: какой квест выдаст NPC при interact', () => {
  const givers = npcPins().filter((p) => p.questIds.length > 0);

  it('первый доступный квест этого NPC; недоступные пропускаются', () => {
    const giver = givers[0];
    const all = () => 'available';
    expect(predictedAccept(giver.templateId, giver.questIds, all)).toBe(giver.questIds[0]);

    const done = () => 'done';
    expect(predictedAccept(giver.templateId, giver.questIds, done)).toBeNull();

    const firstDone = (qid: string) => (qid === giver.questIds[0] ? 'done' : 'available');
    if (giver.questIds.length > 1) {
      expect(predictedAccept(giver.templateId, giver.questIds, firstDone)).toBe(giver.questIds[1]);
    }
  });

  it('чужой список квестов не подменяет правило: NPC без совпадения giverNpcId → null', () => {
    const giver = givers[0];
    const foreign = questOrder.filter((qid) => questDef(qid)?.giverNpcId !== giver.templateId).slice(0, 3);
    expect(predictedAccept(giver.templateId, foreign, () => 'available')).toBeNull();
  });

  it('стартовая цепочка воина существует: квест на forest_wolf, его квестодатель на карте, волк бьётся на 1-м уровне', () => {
    const wolf = questOrder.find((qid) =>
      (questDef(qid)?.objectives ?? []).some(
        (o: { type: string; targetMobId?: string }) => o.type === 'kill' && o.targetMobId === 'forest_wolf',
      ),
    );
    expect(wolf).toBeDefined();
    const pin = npcPins().find((p) => p.questIds.includes(wolf!));
    expect(pin).toBeDefined();
    expect(isQuestCompletable(wolf!)).toBe(true);
    expect(canFightMob('forest_wolf', 1)).toBe(true);
  });
});

describe('кого можно бить на своём уровне', () => {
  it('ровня и ниже — да; выше levelDeltaMax — нет', () => {
    expect(canFightMob('old_greyjaw', 1)).toBe(false); // maxLevel 4 > 1+1
    expect(canFightMob('old_greyjaw', 3)).toBe(true); // 4 <= 3+1
    expect(canFightMob('нет_такого_моба', 1)).toBe(false);
  });
});
