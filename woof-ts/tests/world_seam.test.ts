// Шов мира: агент работает через интерфейс World, а не через Sim напрямую.
// Здесь проверяем две вещи: (1) стенд честно объявляет свои возможности,
// (2) привилегированные методы при отсутствии возможности БРОСАЮТ исключение —
// молчаливого «0 предметов» или «квест доступен» быть не должно (это и есть
// подделка доказательства, из-за которой мы уже получали ложно-зелёные прогоны).
import { describe, expect, it } from 'vitest';

import { SimWorld } from '../src/world/sim_world';
import { describeCapabilities, type WorldCapabilities } from '../src/world/world';
import { gameFacts } from '../src/facts';
import { VIEW_RADIUS } from '../src/world/types';

const make = (over: Partial<Parameters<typeof SimWorld.create>[0]> = {}) =>
  SimWorld.create({
    seed: 42,
    playerClass: 'warrior',
    npcViewRadius: VIEW_RADIUS,
    gathererIdentity: { kind: 'headless', id: 'hl:woof-ts:test' },
    ...over,
  });

/** Подменить объявленные возможности экземпляра — чтобы проверить реакцию методов. */
const withCapabilities = (w: SimWorld, patch: Partial<WorldCapabilities>): SimWorld => {
  const real = w.capabilities;
  Object.defineProperty(w, 'capabilities', { get: () => ({ ...real, ...patch }), configurable: true });
  return w;
};

describe('объявление возможностей стенда', () => {
  it('in-process, детерминированный, RL-словарь действий, без других игроков', () => {
    const c = make().capabilities;
    expect(c.transport).toBe('in-process');
    expect(c.deterministic).toBe(true);
    expect(c.realtime).toBe(false);
    expect(c.otherPlayers).toBe(false);
    expect(c.commandVocabulary).toBe('rl-actions');
    expect(c.latencyMs).toBe(0);
    expect(c.frameSkip).toBe(5);
  });

  it('стенд беднее онлайн-мира, и это заявлено, а не приукрашено', () => {
    const c = make().capabilities;
    expect(c.questStateApi).toBe('full');
    expect(c.entityIdentity).toBe('stable');
    expect(c.entityTemplates).toBe(true);
    expect(c.entityAbsoluteHp).toBe(true);
    expect(c.targetSelection).toBe('nearest-only');
    expect(c.abandonQuest).toBe(false);
    expect(c.vendor).toBe(false);
    expect(c.partyLootRolls).toBe(false);
    const w = make();
    // targetEntity в интерфейсе World опционален: у стенда его нет вовсе.
    expect((w as unknown as { targetEntity?: unknown }).targetEntity).toBeUndefined();
  });

  it('человекочитаемое объявление непустое и содержит транспорт', () => {
    const lines = describeCapabilities(make().capabilities);
    expect(lines.length).toBeGreaterThanOrEqual(3);
    expect(lines.join('\n')).toMatch(/in-process/);
  });

  it('неизвестный класс — исключение при создании мира (druid, кстати, в игре есть)', () => {
    expect(gameFacts().classes).toContain('druid');
    expect(() => make({ playerClass: 'necromancer' })).toThrow(/неизвестный класс/);
  });
});

describe('привилегированные методы не подделывают факты', () => {
  it('questState бросает, если questStateApi=none (молчаливого «доступен» не будет)', () => {
    const w = withCapabilities(make(), { questStateApi: 'none' });
    expect(() => w.questState('q_wolves')).toThrow(/questStateApi=none/);
  });

  it('countItem бросает, если itemCountApi=false (а не возвращает 0)', () => {
    const w = withCapabilities(make(), { itemCountApi: false });
    expect(() => w.countItem('greyjaw_fang')).toThrow(/itemCountApi=false/);
  });

  it('с объявленными возможностями оба метода работают', () => {
    const w = make();
    expect(typeof w.questState('q_wolves')).toBe('string');
    expect(w.countItem('нет_такого_предмета')).toBe(0);
  });

  it('шаг после завершения эпизода — исключение, а не «мир стоит»', () => {
    const w = make({ maxSteps: 5 });
    for (let i = 0; i < 5 && !w.ended; i++) w.stepAction('noop');
    expect(w.ended).not.toBeNull();
    expect(() => w.stepAction('noop')).toThrow(/эпизод завершён/);
  });
});

describe('наблюдение стенда', () => {
  it('боевая видимость ограничена VIEW_RADIUS, а NPC-пины — слой карты', () => {
    const w = make();
    const m = w.observe();
    for (const e of [...m.nearby, ...m.corpses, ...m.objects]) {
      expect(e.dist).toBeLessThanOrEqual(VIEW_RADIUS + 1e-6);
    }
    expect(Array.isArray(m.mapPins)).toBe(true);
    expect(m.mapPins.length).toBeGreaterThan(0);
    expect(m.player.hp).toBeGreaterThan(0);
  });

  it('действие принимается и именем, и индексом — результат один и тот же', () => {
    const a = make();
    const b = make();
    const ra = a.stepAction('noop');
    const rb = b.stepAction(a.actionIndex('noop'));
    expect(ra).toEqual(rb);
  });

  it('неизвестное действие — исключение (словарь команд объявлен)', () => {
    expect(() => make().stepAction('fly_to_moon')).toThrow();
  });
});
