/**
 * agent.ts — главный цикл: OBSERVE -> DECIDE -> EXECUTE -> VERIFY -> LEARN.
 * Порт core/AgentCore.java: те же фазы, тот же журнал, та же строка SUMMARY
 * (чтобы доказательства разных линий сравнивались между собой).
 */
import { ArbitrationLayer } from '../decision/arbitration';
import type { GoalFSM } from '../decision/fsm';
import { SkillLibrary, WorldMemory } from '../memory/memory';
import { SkillExecutor } from '../skills/executor';
import type { World } from '../world/world';
import { activeQuest, type WorldModel } from '../world/types';

export interface AgentOptions {
  /** Печатать строку каждые 10 решений. */
  verbose?: boolean;
  /** Убрать построчный журнал, оставив вехи и SUMMARY. */
  quiet?: boolean;
  /** Печатать каждое решение (диагностика). */
  logEvery?: boolean;
  log?: (line: string) => void;
  interactRange?: number;
}

export interface TurnInEvent {
  step: number;
  worldStep: number;
  questId: string;
  total: number;
}

export interface AgentSummary {
  steps: number;
  worldSteps: number;
  kills: number;
  deaths: number;
  questsDone: number;
  firstTurnInStep: number;
  levelUps: number;
  level: number;
  xp: number;
  copper: number;
  damageDealt: number;
  damageTaken: number;
  ended: string | null;
  phase: string;
  turnIns: TurnInEvent[];
  /** Сколько раз решение не сдвинуло мир и агенту пришлось сделать noop самому.
   *  Ноль — норма: любой навык обязан двигать мир (иначе респавн не наступает). */
  frozenGuards: number;
  skillStats: Record<string, { uses: number; successes: number; lastResult: string }>;
  elapsedMs: number;
}

/** Успех навыка: не провал, не ошибка, не «нет цели», не «не поддерживается». */
export function isOk(result: string | null): boolean {
  if (!result) return false;
  const r = result.toUpperCase();
  return (
    !r.endsWith('_FAILED') &&
    !r.startsWith('ERROR') &&
    !r.startsWith('NO_') &&
    !r.startsWith('UNSUPPORTED') &&
    !r.startsWith('UNKNOWN_SKILL')
  );
}

export class AgentCore {
  private step = 0;
  private kills = 0;
  private deaths = 0;
  private frozenGuards = 0;
  private completedAtStart = 0;
  private lastQuestsDone = 0;
  private firstCompletionStep = -1;
  private readonly turnIns: TurnInEvent[] = [];
  /** Последний известный активный квест. Нужен потому, что сверка идёт ПОСЛЕ шага сдачи:
   *  к этому моменту квест уже закрыт и `fsm.questId` пуст — без этого поля в evidence
   *  попадало `questId: "?"`, то есть доказательство без имени того, что сдано. */
  private lastKnownQuestId: string | null = null;
  private readonly log: (line: string) => void;
  private readonly verbose: boolean;
  private readonly quiet: boolean;
  private readonly logEvery: boolean;
  private readonly interactRange: number;

  constructor(
    readonly world: World,
    readonly fsm: GoalFSM,
    readonly arbitration: ArbitrationLayer,
    readonly executor: SkillExecutor,
    readonly memory: WorldMemory,
    readonly library: SkillLibrary,
    opts: AgentOptions = {},
  ) {
    this.log = opts.log ?? ((s) => console.log(s));
    this.verbose = opts.verbose ?? true;
    this.quiet = opts.quiet ?? false;
    this.logEvery = opts.logEvery ?? false;
    this.interactRange = opts.interactRange ?? world.facts.interactRange;
  }

  get steps(): number {
    return this.step;
  }

  run(maxSteps = 0): AgentSummary {
    const started = Date.now();
    const w0 = this.world.observe();
    this.completedAtStart = w0.counters.questsCompleted;
    this.lastQuestsDone = this.completedAtStart;
    this.info(`loop start: quests_done=${this.completedAtStart}`);

    while ((maxSteps <= 0 || this.step < maxSteps) && !this.world.ended) {
      this.step++;
      const w = this.world.observe();

      if (w.player.dead) {
        // В headless-мире воскрешает само действие (obs.ts: releaseSpirit +
        // resurrectAtSpiritHealer), отдельного respawn не нужно.
        this.info('dead -> воскрешение у Spirit Healer на следующем действии');
      }

      this.rememberQuestTargets(w); // LEARN: где живёт цель квеста
      this.fsm.syncFrom(w, this.interactRange); // фаза из наблюдения, не вручную
      // Запоминаем имя активного квеста, пока оно известно: прирост счётчика сдач виден
      // на следующем шаге, когда квест уже закрыт и фаза пуста.
      if (this.fsm.questId) this.lastKnownQuestId = this.fsm.questId;

      const worldBefore = this.world.step;
      const skill = this.arbitration.decide(w); // DECIDE
      const result = this.executor.execute(skill, w); // EXECUTE
      // Инвариант «решение двигает мир»: навык, который ничего не сделал,
      // останавливает время — респавн не наступает, квест не двигается. Не молчим:
      // считаем, пишем в журнал и делаем канонический noop сами.
      if (this.world.step === worldBefore && !this.world.ended) {
        this.frozenGuards++;
        this.info(`ВНИМАНИЕ: решение не сдвинуло мир (skill=${skill} result=${result}) — принудительный noop`);
        this.world.stepAction('noop');
      }
      const ok = isOk(result);
      this.arbitration.reportResult(skill, ok);
      this.library.record(skill, ok, result);
      this.verify(w); // VERIFY

      if (this.verbose && !this.quiet && (this.logEvery || this.step % 10 === 0)) {
        const cd = this.arbitration.onCooldown;
        this.info(
          `step=${this.step} world=${this.world.step} phase=${this.fsm.phase} skill=${skill} result=${result} ` +
            `hp=${Math.round((w.player.hp / Math.max(1, w.player.maxHp)) * 100)}% lvl=${w.player.level} ` +
            `kills=${w.counters.kills} deaths=${w.counters.deaths} quests=${w.counters.questsCompleted} ` +
            `nearby=${w.nearby.length} npcs=${w.npcs.length}` +
            (cd.length ? ` cooldown=${cd.join(',')}` : ''),
        );
      }
    }
    return this.summary(started);
  }

  /** Запомнить координаты ближайшего ЖИВОГО моба — цели активного квеста. */
  private rememberQuestTargets(w: WorldModel): void {
    const q = activeQuest(w);
    if (!q) return;
    const wanted = q.objectives.find((o) => o.type === 'kill')?.targetMobId;
    const mob = wanted ? w.nearby.find((m) => m.templateId === wanted) : undefined;
    if (mob) {
      this.memory.saveQuestMobCoord(q.id, { x: mob.x, z: mob.z });
      this.memory.saveMobSpot(mob.templateId, { x: mob.x, z: mob.z });
    }
  }

  private verify(w: WorldModel): void {
    if (w.counters.kills > this.kills) {
      if (this.verbose && !this.quiet) this.info(`kill total=${w.counters.kills}`);
      this.kills = w.counters.kills;
    }
    if (w.counters.deaths > this.deaths) {
      this.info(`death total=${w.counters.deaths}`);
      this.deaths = w.counters.deaths;
    }
    this.lastQuestsDone = w.counters.questsCompleted;
    if (this.firstCompletionStep < 0 && w.counters.questsCompleted > this.completedAtStart) {
      this.firstCompletionStep = this.step;
      const questId = this.fsm.questId ?? this.lastKnownQuestId ?? '?';
      this.turnIns.push({
        step: this.step,
        worldStep: this.world.step,
        questId,
        total: w.counters.questsCompleted,
      });
      this.info(`QUEST TURNED IN at step ${this.step} (total ${w.counters.questsCompleted})`);
    }
  }

  private summary(started: number): AgentSummary {
    const w = this.world.observe();
    const done = Math.max(this.fsm.completionCount, Math.max(0, this.lastQuestsDone - this.completedAtStart));
    const out: AgentSummary = {
      steps: this.step,
      worldSteps: this.world.step,
      kills: w.counters.kills,
      deaths: w.counters.deaths,
      questsDone: done,
      firstTurnInStep: this.firstCompletionStep,
      levelUps: w.counters.levelUps,
      level: w.player.level,
      xp: w.player.xp,
      copper: w.copper,
      damageDealt: w.counters.damageDealt,
      damageTaken: w.counters.damageTaken,
      ended: this.world.ended,
      phase: this.fsm.phase,
      turnIns: this.turnIns,
      frozenGuards: this.frozenGuards,
      skillStats: this.library.snapshot(),
      elapsedMs: Date.now() - started,
    };
    this.info(
      `SUMMARY steps=${out.steps} world_steps=${out.worldSteps} kills=${out.kills} deaths=${out.deaths} ` +
        `quests_done=${out.questsDone}` +
        (out.firstTurnInStep > 0 ? ` first_turn_in_step=${out.firstTurnInStep}` : '') +
        (out.frozenGuards > 0 ? ` frozen_guards=${out.frozenGuards}` : ''),
    );
    return out;
  }

  private info(msg: string): void {
    if (this.verbose) this.log(`[Agent] ${msg}`);
  }
}
