// Детерминизм и «живость» эпизода: тот же сид обязан давать побайтово тот же
// эпизод (метрики И трассу решений), а каждое решение — двигать мир.
// Это то, на чём держится воспроизводимость evidence и вообще смысл тюнинга:
// если разница между прогонами есть при равных параметрах, сравнивать нечего.
import { describe, expect, it } from 'vitest';

import type { AgentSummary } from '../src/core/agent';
import { buildAgent, unsupportedReasons } from '../src/core/build';
import { SimWorld } from '../src/world/sim_world';
import { VIEW_RADIUS } from '../src/world/types';

const runOnce = (seed: number, steps: number): { s: AgentSummary; lines: string[] } => {
  const world = SimWorld.create({
    seed,
    playerClass: 'warrior',
    npcViewRadius: VIEW_RADIUS,
    gathererIdentity: { kind: 'headless', id: `hl:woof-ts:test:${seed}` },
  });
  const lines: string[] = [];
  const { agent } = buildAgent(world, {
    verbose: true,
    quiet: false,
    logEvery: true,
    log: (l) => lines.push(l),
    unsupportedSkills: Object.keys(unsupportedReasons('warrior')),
  });
  return { s: agent.run(steps), lines };
};

const projection = (s: AgentSummary) => ({
  steps: s.steps,
  worldSteps: s.worldSteps,
  kills: s.kills,
  deaths: s.deaths,
  questsDone: s.questsDone,
  firstTurnInStep: s.firstTurnInStep,
  levelUps: s.levelUps,
  level: s.level,
  xp: s.xp,
  copper: s.copper,
  damageDealt: s.damageDealt,
  damageTaken: s.damageTaken,
  ended: s.ended,
  phase: s.phase,
  frozenGuards: s.frozenGuards,
  turnIns: s.turnIns,
  skillStats: s.skillStats,
});

describe('воспроизводимость', () => {
  it('один сид → идентичные метрики и идентичная трасса решений', () => {
    const a = runOnce(42, 25);
    const b = runOnce(42, 25);
    expect(projection(b.s)).toEqual(projection(a.s));
    expect(b.lines).toEqual(a.lines);
    expect(a.lines.length).toBeGreaterThan(20); // трасса действительно писалась
  });

  it('другой сид → другой эпизод (иначе тест выше ничего не измерял бы)', () => {
    const a = runOnce(42, 25);
    const c = runOnce(7, 25);
    expect(projection(c.s)).not.toEqual(projection(a.s));
  });
});

describe('эпизод двигает мир', () => {
  it('каждое решение двигает мир: worldSteps >= steps × frameSkip, frozenGuards = 0', () => {
    // Одно РЕШЕНИЕ агента — это целый навык, а навык исполняет цикл действий мира
    // (navigate/attack бьют по много раз), поэтому мировых шагов заметно больше,
    // чем решений × frameSkip. Важно обратное: меньше быть не может, и ни одно
    // решение не должно пройти впустую (frozenGuards = 0 — иначе респавн не
    // наступает и эпизод замирает).
    const { s } = runOnce(42, 25);
    expect(s.worldSteps).toBeGreaterThanOrEqual(25 * 5);
    expect(s.frozenGuards).toBe(0);
    expect(s.ended).toBeNull();
  });

  it('за 25 решений воин успевает взять и начать сдавать стартовый квест', () => {
    // Заявленная цепочка: q_hub_know_your_numbers у Hale виден на спавне,
    // 10 ударов по манекену, сдача на шаге ~11-12.
    const { s } = runOnce(42, 25);
    expect(s.firstTurnInStep).toBeGreaterThan(0);
    expect(s.firstTurnInStep).toBeLessThanOrEqual(20);
  });
});
