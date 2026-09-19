/**
 * browser_agent.ts — цикл агента для мира В БРАУЗЕРЕ (задача C1, приёмка C1.6=J8).
 *
 * Почему отдельный цикл, а не `AgentCore`: `AgentCore.run()` синхронный (шов
 * `World`), а CDP — запрос/ответ. Подделывать синхронность значило бы либо
 * блокировать событие, либо молча возвращать устаревшее наблюдение. Поэтому здесь
 * тот же контур — НАБЛЮДАЙ → ПОМНИ → РЕШАЙ → ДЕЙСТВУЙ → ПРОВЕРЬ — но асинхронный,
 * и слой решений переиспользуется БЕЗ изменений: `GoalFSM.syncFrom(w)` и
 * `ArbitrationLayer.decide(w)` чисты по `WorldModel` и не знают про транспорт.
 *
 * Композиты (navigate/return_to_giver/explore/flee/noop) исполняются здесь, потому
 * что в браузере они состоят из нескольких тиков ввода (`controller.move`) с
 * гистерезисом курса, а не из одного RL-действия.
 *
 * Честность: каждый навык возвращает токен результата в конвенции исполнителя
 * стенда ('OK…', 'NO_…', 'NOT_IN_RANGE…', 'UNSUPPORTED:…', 'ERROR:…'). Провал
 * уходит в `arbitration.reportResult(skill, false)` и в `SkillLibrary` — то есть
 * контур самоулучшения видит браузерный мир так же, как стенд.
 */
import { ArbitrationLayer } from '../decision/arbitration';
import { GoalFSM } from '../decision/fsm';
import { allCamps, campsFor, npcPins } from '../facts';
import { WorldMemory, SkillLibrary } from '../memory/memory';
import { canonical } from '../skills/canon';
import { nearestAvailableGiver, nearestTurnInNpc, readyQuest, activeQuest, type WorldModel } from '../world/types';
import type { BrowserWorld } from '../world/browser_world';

export interface BrowserAgentOptions {
  maxSteps?: number;
  log?: (line: string) => void;
  verbose?: boolean;
  logEvery?: boolean;
  /** Пауза между тиками (в тесте — мгновенная, без реальных таймеров). */
  sleep?: (ms: number) => Promise<void>;
  /** Сколько тиков ввода разрешено на один поход (эталон: 80). */
  navMaxTicks?: number;
  /** Ограничение прогона по времени, мс (0 = без ограничения). */
  maxMs?: number;
}

export interface TurnInEvent {
  step: number;
  questId: string;
  npc: string;
}

export interface BrowserSummary {
  steps: number;
  kills: number;
  deaths: number;
  questsDone: number;
  firstTurnInStep: number;
  levelUps: number;
  level: number;
  ended: string | null;
  phase: string;
  turnIns: TurnInEvent[];
  /** Каких методов страницы не хватило (честный список, а не «вроде работало»). */
  missingApi: string[];
  unknownKinds: Record<string, number>;
  latencyMs: number;
  ms: number;
}

/** Тот же критерий «результат = успех», что и в `AgentCore`. */
function isOk(result: string): boolean {
  return (
    !!result &&
    !result.startsWith('ERROR') &&
    !result.startsWith('NO_') &&
    !result.startsWith('NOT_IN_RANGE') &&
    !result.startsWith('STUCK') &&
    !result.startsWith('TIMEOUT') &&
    !result.startsWith('UNSUPPORTED') &&
    !result.startsWith('UNKNOWN_SKILL')
  );
}

export class BrowserAgent {
  private step = 0;
  private firstTurnInStep = -1;
  private lastQuestsDone = 0;
  private lastKnownQuestId: string | null = null;
  private readonly turnIns: TurnInEvent[] = [];
  private readonly log: (line: string) => void;
  private readonly verbose: boolean;
  private readonly logEvery: boolean;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly navMaxTicks: number;
  private readonly maxMs: number;
  private readonly interactRange: number;

  constructor(
    readonly world: BrowserWorld,
    readonly fsm: GoalFSM,
    readonly arbitration: ArbitrationLayer,
    readonly memory: WorldMemory,
    readonly library: SkillLibrary,
    opts: BrowserAgentOptions = {},
  ) {
    this.log = opts.log ?? ((s) => console.log(s));
    this.verbose = opts.verbose ?? true;
    this.logEvery = opts.logEvery ?? false;
    this.sleep = opts.sleep ?? ((ms) => new Promise<void>((r) => setTimeout(r, ms)));
    this.navMaxTicks = opts.navMaxTicks ?? 80;
    this.maxMs = opts.maxMs ?? 0;
    this.interactRange = world.facts.interactRange;
  }

  get steps(): number {
    return this.step;
  }

  async run(maxSteps = 0): Promise<BrowserSummary> {
    const started = Date.now();
    const limit = maxSteps > 0 ? maxSteps : (this.world.ended ? 0 : 200);
    const w0 = await this.world.observe();
    this.lastQuestsDone = w0.counters.questsCompleted;
    this.info(`loop start: quests_done=${this.lastQuestsDone} pos=(${w0.player.x.toFixed(1)}, ${w0.player.z.toFixed(1)}) hp=${w0.player.hp}/${w0.player.maxHp} lvl=${w0.player.level}`);

    while ((limit <= 0 || this.step < limit) && !this.world.ended) {
      if (this.maxMs > 0 && Date.now() - started > this.maxMs) {
        this.world.close(`TIME_LIMIT: ${this.maxMs} мс`);
        break;
      }
      this.step++;
      const w = await this.world.observe();

      if (w.player.dead) {
        this.info('dead -> respawn');
        const r = await this.world.act('respawn', w);
        this.info(`respawn: ${r}`);
      }

      this.rememberTargets(w);
      this.fsm.syncFrom(w, this.interactRange);
      if (this.fsm.questId) this.lastKnownQuestId = this.fsm.questId;

      const skill = this.arbitration.decide(w); // DECIDE
      const result = await this.execute(skill, w); // EXECUTE (асинхронно)
      const ok = isOk(result);
      this.arbitration.reportResult(skill, ok);
      this.library.record(skill, ok, result);
      this.verifyTurnIns(w); // VERIFY

      if (this.verbose && (this.logEvery || this.step % 10 === 0)) {
        this.info(
          `step=${this.step} phase=${this.fsm.phase} skill=${skill} result=${result} ` +
            `hp=${Math.round((w.player.hp / Math.max(1, w.player.maxHp)) * 100)}% lvl=${w.player.level} ` +
            `kills=${w.counters.kills} deaths=${w.counters.deaths} quests=${w.counters.questsCompleted} ` +
            `nearby=${w.nearby.length} npcs=${w.npcs.length} pos=(${w.player.x.toFixed(1)}, ${w.player.z.toFixed(1)})`,
        );
      }
      await this.sleep(this.world.navTickMs);
    }

    const last = this.world.lastObservation;
    const missing = Object.entries(this.world.pageApi)
      .filter(([, v]) => v !== 'function')
      .map(([k, v]) => `${k}=${v}`);
    return {
      steps: this.step,
      kills: this.world.counters.kills,
      deaths: this.world.counters.deaths,
      questsDone: this.world.counters.questsCompleted,
      firstTurnInStep: this.firstTurnInStep,
      levelUps: this.world.counters.levelUps,
      level: last?.player.level ?? 0,
      ended: this.world.ended ?? (this.step >= limit && limit > 0 ? 'MAX_STEPS' : 'STOPPED'),
      phase: this.fsm.phase,
      turnIns: [...this.turnIns],
      missingApi: missing,
      unknownKinds: { ...this.world.unknownKinds },
      latencyMs: this.world.capabilities.latencyMs,
      ms: Date.now() - started,
    };
  }

  /** Запомнить координаты живых целей: лагеря мобов и позиции квестодателей. */
  private rememberTargets(w: WorldModel): void {
    const q = activeQuest(w);
    if (q) {
      const kill = q.objectives.find((o) => o.type === 'kill' && o.targetMobId && o.have < o.required);
      if (kill?.targetMobId) {
        const mob = w.nearby.find((m) => m.templateId === kill.targetMobId && !m.dead);
        if (mob) this.memory.saveQuestMobCoord(q.id, { x: mob.x, z: mob.z });
      }
    }
    for (const n of w.npcs) {
      if (n.completableQuests.length > 0) this.memory.rememberGiver(n.templateId, { x: n.x, z: n.z });
    }
    for (const c of w.corpses) this.memory.saveMobSpot(c.templateId, { x: c.x, z: c.z });
  }

  /** Прирост счётчика сдач — событие с именем квеста (иначе в evidence «questId: ?»). */
  private verifyTurnIns(w: WorldModel): void {
    const done = w.counters.questsCompleted;
    if (done > this.lastQuestsDone) {
      const questId = this.lastKnownQuestId ?? readyQuest(w)?.id ?? '?';
      const npc = nearestTurnInNpc(w, readyQuest(w))?.templateId ?? '?';
      this.turnIns.push({ step: this.step, questId, npc });
      if (this.firstTurnInStep < 0) this.firstTurnInStep = this.step;
      this.info(`[Agent] QUEST TURNED IN at step ${this.step} (${questId}, total ${done})`);
      this.lastQuestsDone = done;
    }
  }

  /** Исполнение навыка: композиты — здесь, канон — через `world.act`. */
  async execute(name: string, w: WorldModel): Promise<string> {
    let skill: string;
    try {
      skill = canonical(name);
    } catch (e) {
      return `UNKNOWN_SKILL:${name} (${(e as Error).message})`;
    }
    try {
      switch (skill) {
        case 'navigate':
          return this.navigate(w);
        case 'return_to_giver':
          return this.turnIn(w);
        case 'explore':
          return this.explore(w);
        case 'flee': {
          const first = await this.world.act('flee', w);
          for (let i = 0; i < 3; i++) await this.world.move({ forward: true }, null);
          return first;
        }
        case 'farm': {
          // Цель может быть дальше радиуса атаки: сначала подход, потом удар.
          const target = nearestQuestMobOrHostile(w);
          if (target && target.dist > this.world.facts.meleeRange) {
            const go = await this.world.navigateTo(target.x, target.z, {
              maxTicks: Math.min(this.navMaxTicks, 40),
              arriveYards: Math.max(3, this.world.facts.meleeRange - 1),
              sleep: this.sleep,
            });
            if (!go.arrived) return `${go.reason} (подход к ${target.templateId})`;
          }
          return this.world.act('farm', w);
        }
        default:
          return this.world.act(skill, w);
      }
    } catch (e) {
      return `ERROR:${(e as Error).message}`;
    }
  }

  /** Куда идти: сдача → цель активного квеста → квестодатель → разведка. */
  private async navigate(w: WorldModel): Promise<string> {
    const ready = readyQuest(w);
    if (ready) {
      const live = nearestTurnInNpc(w, ready);
      const pin = ready.turnInNpcId ? npcPins().find((p) => p.templateId === ready.turnInNpcId) : null;
      const x = live?.x ?? pin?.x;
      const z = live?.z ?? pin?.z;
      if (x == null || z == null) return `NO_TURNIN_NPC: не знаю, где ${ready.turnInNpcId ?? ready.id}`;
      const go = await this.world.navigateTo(x, z, { maxTicks: this.navMaxTicks, sleep: this.sleep });
      if (!go.arrived) return `${go.reason} (поход к ${ready.turnInNpcId})`;
      const after = await this.world.observe();
      return this.world.act('turn_in_quest', after);
    }
    const active = activeQuest(w);
    if (active) {
      const kill = active.objectives.find((o) => o.type === 'kill' && o.targetMobId && o.have < o.required);
      const collect = active.objectives.find((o) => o.type === 'collect' && o.have < o.required);
      const mobId = kill?.targetMobId ?? null;
      const remembered = mobId ? this.memory.questMobCoord(active.id) : null;
      const camp = mobId ? campsFor(mobId).sort((a, b) => Math.hypot(a.x - w.player.x, a.z - w.player.z) - Math.hypot(b.x - w.player.x, b.z - w.player.z))[0] : null;
      const spot = mobId ? this.memory.mobSpot(mobId) : null;
      const x = remembered?.x ?? camp?.x ?? spot?.x;
      const z = remembered?.z ?? camp?.z ?? spot?.z;
      if (x != null && z != null) {
        const go = await this.world.navigateTo(x, z, { maxTicks: this.navMaxTicks, sleep: this.sleep });
        return go.arrived ? `ARRIVED: лагерь ${mobId} (${x.toFixed(1)}, ${z.toFixed(1)})` : `${go.reason} (поход к лагерю ${mobId})`;
      }
      if (collect) return `NO_ROUTE: цель collect (${collect.itemId ?? '?'}) — нужен навык loot/подход, координат нет`;
      return `NO_ROUTE: активен ${active.id}, но цели не знаю`;
    }
    const giver = nearestAvailableGiver(w);
    if (giver) {
      const go = await this.world.navigateTo(giver.x, giver.z, {
        maxTicks: this.navMaxTicks,
        arriveYards: Math.max(2, this.interactRange - 2),
        sleep: this.sleep,
      });
      if (!go.arrived) return `${go.reason} (поход к ${giver.templateId})`;
      const after = await this.world.observe();
      return this.world.act('accept_quest', after);
    }
    // Квестодателя не видно: идём к ближайшему пину из контента игры.
    const pin = npcPins()
      .filter((p) => p.questIds.length > 0 && !this.memory.isGiverExhausted(p.templateId))
      .map((p) => ({ ...p, live: w.npcs.find((n) => n.templateId === p.templateId) }))
      .map((p) => ({ ...p, x: p.live?.x ?? p.x, z: p.live?.z ?? p.z }))
      .sort((a, b) => Math.hypot(a.x - w.player.x, a.z - w.player.z) - Math.hypot(b.x - w.player.x, b.z - w.player.z))[0];
    if (!pin) return 'NO_GIVER_PIN: в контенте игры нет NPC с квестами';
    const go = await this.world.navigateTo(pin.x, pin.z, {
      maxTicks: this.navMaxTicks,
      arriveYards: Math.max(2, this.interactRange - 2),
      sleep: this.sleep,
    });
    return go.arrived ? `ARRIVED_GIVER: ${pin.templateId} (${pin.x.toFixed(1)}, ${pin.z.toFixed(1)})` : `${go.reason} (поход к пину ${pin.templateId})`;
  }

  /** Возврат к сдаче: то же, что navigate при готовом квесте, но без ветки приёма. */
  private async turnIn(w: WorldModel): Promise<string> {
    const ready = readyQuest(w);
    if (!ready) return 'NO_READY_QUEST: возвращаться не с чем';
    return this.navigate(w);
  }

  /** Разведка: лагеря из контента игры, которые ещё не посещены. Без блуждания
   *  «наугад» — цель всегда из фактов (лагерь моба или пин NPC). */
  private async explore(w: WorldModel): Promise<string> {
    const camps = allCamps()
      .map((c) => ({ ...c, d: Math.hypot(c.x - w.player.x, c.z - w.player.z) }))
      .filter((c) => !this.memory.wasVisited(c.x, c.z))
      .sort((a, b) => a.d - b.d);
    const target = camps[0];
    if (!target) return 'NO_EXPLORE_TARGET: все известные лагеря посещены';
    this.memory.markVisited(target.x, target.z);
    const go = await this.world.navigateTo(target.x, target.z, { maxTicks: this.navMaxTicks, sleep: this.sleep });
    return go.arrived
      ? `EXPLORE_ARRIVED: лагерь ${target.mobId} (${target.x.toFixed(1)}, ${target.z.toFixed(1)})`
      : `${go.reason} (разведка лагеря ${target.mobId})`;
  }

  private info(line: string): void {
    this.log(`[Agent] ${line}`);
  }
}

/** Цель боя: моб цели активного квеста, иначе ближайший враждебный живой. */
function nearestQuestMobOrHostile(w: WorldModel) {
  const active = activeQuest(w);
  const wanted = new Set(
    (active?.objectives ?? []).filter((o) => o.type === 'kill' && o.targetMobId && o.have < o.required).map((o) => o.targetMobId as string),
  );
  const alive = w.nearby.filter((m) => !m.dead && m.hostile && m.hp > 0).sort((a, b) => a.dist - b.dist);
  return alive.find((m) => wanted.has(m.templateId)) ?? alive[0] ?? null;
}

/** Собрать агент поверх браузерного мира (аналог `buildAgent` для стенда). */
export function buildBrowserAgent(world: BrowserWorld, opts: BrowserAgentOptions = {}): BrowserAgent {
  const memory = new WorldMemory();
  const library = new SkillLibrary();
  const fsm = new GoalFSM();
  const ranges = { meleeRange: world.facts.meleeRange, interactRange: world.facts.interactRange };
  const arbitration = new ArbitrationLayer(fsm, memory, ranges, world.capabilities);
  // Навыки, которых в браузерной линии пока нет, — выключаем явно, чтобы арбитраж
  // их не выбирал: честный отказ вместо «попробуем и получим UNSUPPORTED» каждый шаг.
  for (const s of ['sell_junk', 'gather', 'craft', 'craft_item', 'equip', 'buy']) arbitration.disable(s);
  return new BrowserAgent(world, fsm, arbitration, memory, library, opts);
}
