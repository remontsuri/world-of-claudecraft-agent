/**
 * build.ts — сборка агента поверх ЛЮБОГО мира, реализующего интерфейс World.
 *
 * Зачем отдельный файл: состав слоёв политики (память → FSM → арбитраж →
 * исполнитель) не должен зависеть от транспорта мира. Один и тот же buildAgent
 * собирает агента для in-process стенда (SimWorld), для бриджа к headless env
 * upstream (NdjsonBridge) и позже — для живого сервера; различаются только
 * capabilities, которые заявлены до прогона. Побочный, но важный эффект: у
 * тестов появляется точка входа, чтобы гонять всю политику in-process, не спавня
 * процесс и не читая stdout.
 *
 * Пороги политика берёт из src/policy/params.ts (PARAMS) — единой объявленной
 * таблицы; здесь их не задают и не переопределяют.
 */
import { classAbilities } from '../facts';
import { ArbitrationLayer } from '../decision/arbitration';
import { GoalFSM } from '../decision/fsm';
import { SkillLibrary, WorldMemory } from '../memory/memory';
import { CANON, HEADLESS_UNSUPPORTED } from '../skills/canon';
import { SkillExecutor } from '../skills/executor';
import type { World } from '../world/world';
import { AgentCore, type AgentOptions } from './agent';

/** Навыки канона, привязанные к заклинанию конкретного класса. */
const CLASS_SPELL_SKILLS: ReadonlyArray<readonly [skill: string, spell: string]> = [
  ['cast_frostbolt', 'frostbolt'],
  ['cast_fireball', 'fireball'],
];

/**
 * Какие навыки канона невыполнимы и ПОЧЕМУ (заявляется до прогона, пишется в
 * evidence). Две причины: (1) в headless action space этого нет вовсе —
 * явный CUT upstream; (2) класс не знает нужное заклинание — набор класса
 * берём из данных игры, не выдумываем.
 */
export function unsupportedReasons(playerClass: string): Record<string, string> {
  const abilities = classAbilities(playerClass);
  const reasons: Record<string, string> = {};
  for (const s of CANON) if (HEADLESS_UNSUPPORTED[s]) reasons[s] = HEADLESS_UNSUPPORTED[s];
  for (const [skill, spell] of CLASS_SPELL_SKILLS) {
    if (!abilities.includes(spell)) {
      reasons[skill] =
        `класс ${playerClass} не знает "${spell}" ` +
        `(в наборе класса ${abilities.length} способностей)`;
    }
  }
  return reasons;
}

export interface BuildOptions extends AgentOptions {
  /** Навыки, которые мир не поддерживает: арбитраж их отключит. */
  unsupportedSkills?: readonly string[];
}

export interface BuiltAgent {
  readonly world: World;
  readonly fsm: GoalFSM;
  readonly arbitration: ArbitrationLayer;
  readonly executor: SkillExecutor;
  readonly memory: WorldMemory;
  readonly library: SkillLibrary;
  readonly agent: AgentCore;
}

export function buildAgent(world: World, opts: BuildOptions = {}): BuiltAgent {
  const memory = new WorldMemory();
  const library = new SkillLibrary();
  const fsm = new GoalFSM();
  const ranges = {
    meleeRange: world.facts.meleeRange,
    interactRange: world.facts.interactRange,
  };
  const arbitration = new ArbitrationLayer(fsm, memory, ranges, world.capabilities);
  for (const s of opts.unsupportedSkills ?? []) arbitration.disable(s);
  const executor = new SkillExecutor(world, memory, ranges);
  const agent = new AgentCore(world, fsm, arbitration, executor, memory, library, opts);
  return { world, fsm, arbitration, executor, memory, library, agent };
}
