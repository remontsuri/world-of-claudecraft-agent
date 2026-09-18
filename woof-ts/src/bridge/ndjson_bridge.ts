/**
 * ndjson_bridge.ts — мир за бриджем: headless env server игры как транспорт.
 *
 * Это второй транспорт после in-process стенда (SimWorld) и первый, который
 * доказывает, что шов World настоящий: агент работает с миром, живущим В ДРУГОМ
 * ПРОЦЕССЕ, и видит его ровно так, как мир сам себя показывает — через RL-obs
 * (607 чисел) и `info` (счётчики). Никаких привилегий стенда здесь нет:
 * ни глобального зрения, ни id сущностей, ни абсолютного HP мобов.
 *
 * Что по проводу есть и как мы это используем:
 *   obs.self        → hp-доля, уровень, xp-доля, АБСОЛЮТНЫЕ координаты игрока
 *                     (восстанавливаются из x/WORLD_MAX_X и z-нормали + границ мира),
 *                     курс, GCD, каст, смерть/бой/автоатака/отдых;
 *   obs.abilities   → готовность и кулдауны по слотам; id способности — из набора
 *                     класса (клиент знает свою книгу заклинаний: статические данные);
 *   obs.target      → доля HP цели, Δуровня, дистанция, пеленг, hostile/lootable/агро;
 *   obs.mobs[5]     → живые враждебные мобы в 60 ярдах: дистанция, пеленг, доля HP,
 *                     Δуровня, агро (пустой слот = дистанция 60, см. bridge/obs.ts);
 *   obs.interactable→ ОДИН ближайший объект в INTERACT_RANGE: труп / объект / NPC;
 *   obs.quests      → состояние и доля выполнения КАЖДОГО квеста игры.
 *   info            → level, xp, hp, kills, deaths, quests_done, copper, step.
 *
 * Чего по проводу НЕТ (объявлено в capabilities, а не подделано):
 *   - id и вид (templateId) сущностей → entityIdentity='slot', entityTemplates=false.
 *     Позиция в списке НЕ личность: между кадрами слоты переставляются.
 *     Вид моба не узнать — значит «тот ли это моб, которого требует квест» по
 *     наблюдению не проверяется; политика идёт к лагерю из контент-данных и бьёт то,
 *     что там есть. Это заявленное отличие, а не баг.
 *   - абсолютное HP сущностей → entityAbsoluteHp=false (hp хранится долей, maxHp=1);
 *   - накопленный урон → damageCounters=false (counters.damageDealt/Taken = 0,
 *     ветки политики, которые на них смотрят, просто не срабатывают — kills работают);
 *   - состояние квеста 'available' → questStateApi='observed': в obs ноль
 *     НЕРАЗЛИЧИМ между available и none/failed, поэтому мы возвращаем 'other'
 *     и никогда не утверждаем доступность (угадывание = подделка доказательства);
 *   - число предметов в сумках → itemCountApi=false: countItem() бросает исключение;
 *   - per-objective счётчики квеста → questObjectiveCounts=false: для квестов с одной
 *     целью have выводится из наблюдаемой доли точно, для многоцельных ставим 0
 *     (консервативно: «нужно всё»), а не выдумываем числа.
 *
 * Откуда тогда берётся знание «где квестодатель»: из статического контента игры
 * (слой карты, как у клиента) + восстановленных координат игрока. NPC в пределах
 * INTERACT_RANGE идентифицируется по ближайшему пину карты — это вывод из
 * наблюдения и данных, а не чтение чужой памяти.
 */
import { INTERACT_RANGE_YARDS, TICK_SECONDS, gameFacts, knownAbilities, npcPins, questDef, questOrder, type GameFacts } from '../facts';
import { isQuestCompletable, questPriority } from '../world/quest_policy';
import { VIEW_RADIUS, type Counters, type EntityView, type MapPin, type ObjectiveView, type PlayerView, type QuestStateName, type QuestView, type WorldModel } from '../world/types';
import type { AbilityView, StepResult } from '../world/sim_world';
import type { World, WorldCapabilities } from '../world/world';
import { EnvClient, type EnvEpisodeConfig } from './env_client';
import { decodeObs, type DecodedObs } from './obs';

export interface NdjsonBridgeOptions {
  seed: number;
  playerClass?: string;
  playerLevel?: number;
  /** Тиков мира на одно решение (у upstream по умолчанию 5). */
  frameSkip?: number;
  /** Лимит шагов мира; 0 = без лимита (эпизод ограничивают решения агента). */
  maxSteps?: number;
  respawnSeconds?: number;
  /** Завершать эпизод на смерти (у env по умолчанию true). */
  terminateOnDeath?: boolean;
  /** Готовый клиент (для тестов); иначе создаём по spec. */
  client?: EnvClient;
  spec?: { command: string; args: string[]; cwd?: string };
}

/** Синтетические id: по проводу личности сущностей нет, поэтому id отрицательные —
 *  их невозможно перепутать с настоящими id мира (они у игры положительные). */
const ID_TARGET = -1001;
const ID_INTERACTABLE = -2001;
const idMobSlot = (k: number) => -(k + 1);

interface PinRecord {
  templateId: string;
  name: string;
  x: number;
  z: number;
  questIds: string[];
}

export class NdjsonBridge implements World {
  readonly facts: GameFacts = gameFacts();
  private readonly client: EnvClient;
  private readonly opts: Required<Pick<NdjsonBridgeOptions, 'seed' | 'playerClass' | 'playerLevel' | 'frameSkip' | 'maxSteps' | 'respawnSeconds' | 'terminateOnDeath'>>;
  private obs: number[];
  private decoded: DecodedObs;
  private info: { level: number; xp: number; hp: number; kills: number; deaths: number; quests_done: number; copper: number; step: number };
  private prevInfo = { kills: 0, deaths: 0, quests_done: 0, copper: 0, xp: 0, level: 1 };
  private startLevel = 1;
  private lastMaxHp = 0;
  private endedReason: string | null = null;
  private lastReward = 0;
  private lastTerminated = false;
  private lastTruncated = false;
  private readonly pins: PinRecord[];

  constructor(options: NdjsonBridgeOptions) {
    this.opts = {
      seed: options.seed,
      playerClass: options.playerClass ?? 'warrior',
      playerLevel: options.playerLevel ?? 1,
      frameSkip: options.frameSkip ?? 5,
      maxSteps: options.maxSteps ?? 0,
      respawnSeconds: options.respawnSeconds ?? 15,
      terminateOnDeath: options.terminateOnDeath ?? true,
    };
    if (!options.client && !options.spec) {
      throw new Error('нужен либо готовый client, либо spec (command/args) процесса мира');
    }
    this.client = options.client ?? EnvClient.spawn({ spec: options.spec! });
    const config: EnvEpisodeConfig = {
      frameSkip: this.opts.frameSkip,
      maxSteps: this.opts.maxSteps,
      respawnSeconds: this.opts.respawnSeconds,
      terminateOnDeath: this.opts.terminateOnDeath,
    };
    const r = this.client.reset({
      seed: this.opts.seed,
      playerClass: this.opts.playerClass,
      playerLevel: this.opts.playerLevel,
      config,
    });
    this.obs = r.obs;
    this.info = r.info;
    this.startLevel = r.info.level;
    this.prevInfo = { ...r.info };
    this.decoded = decodeObs(this.obs, this.opts.playerClass, this.facts);
    this.lastMaxHp = this.decoded.hpFrac > 0 ? r.info.hp / this.decoded.hpFrac : r.info.hp;
    this.pins = npcPins().map((p) => ({ templateId: p.templateId, name: p.name, x: p.x, z: p.z, questIds: p.questIds }));
  }

  /** Действия мира — из ответа info (проверены на совпадение с деревом игры). */
  get actions(): readonly string[] {
    return this.client.info.actions;
  }

  get step(): number {
    return this.info.step;
  }

  get ended(): string | null {
    return this.endedReason;
  }

  get copper(): number {
    return this.info.copper;
  }

  /** Награда env за последний шаг (для диагностики/обучения; политика её не использует). */
  get reward(): number {
    return this.lastReward;
  }

  get capabilities(): WorldCapabilities {
    return {
      transport: 'ndjson-stdio',
      absoluteCoords: true, // координаты игрока и сущностей восстанавливаются из obs
      questStateApi: 'observed',
      itemCountApi: false,
      contentData: true,
      deterministic: true,
      frameSkip: this.opts.frameSkip,
      realtime: false,
      otherPlayers: false,
      targetSelection: 'nearest-only',
      abandonQuest: false,
      vendor: false,
      partyLootRolls: false,
      commandVocabulary: 'rl-actions',
      entityIdentity: 'slot',
      entityTemplates: false,
      entityAbsoluteHp: false,
      damageCounters: false,
      questObjectiveCounts: false,
      latencyMs: 0,
    };
  }

  actionIndex(name: string): number {
    const idx = (this.client.info.actions as readonly string[]).indexOf(name);
    if (idx < 0) {
      throw new Error(`в мире нет действия "${name}" (доступно ${this.client.info.num_actions})`);
    }
    return idx;
  }

  stepAction(action: string | number): StepResult {
    if (this.endedReason) {
      throw new Error(`эпизод завершён (${this.endedReason}); дальнейшие шаги невозможны`);
    }
    const idx = typeof action === 'number' ? action : this.actionIndex(action);
    const name = typeof action === 'number' ? (this.actions[idx] ?? `#${idx}`) : action;
    if (idx < 0 || idx >= this.client.info.num_actions) {
      throw new Error(`действие ${idx} вне словаря мира (0..${this.client.info.num_actions - 1})`);
    }
    const before = this.counters;
    const reply = this.client.step(idx);
    this.obs = reply.obs;
    this.info = reply.info;
    this.decoded = decodeObs(this.obs, this.opts.playerClass, this.facts);
    this.lastReward = reply.reward;
    this.lastTerminated = reply.terminated;
    this.lastTruncated = reply.truncated;
    if (this.decoded.hpFrac > 0) this.lastMaxHp = reply.info.hp / this.decoded.hpFrac;
    const after = this.counters;
    this.prevInfo = { ...reply.info };

    if (reply.terminated) {
      this.endedReason = this.decoded.dead
        ? 'terminated:death'
        : this.info.level >= this.facts.maxLevel
          ? 'terminated:max-level'
          : 'terminated:world';
    } else if (reply.truncated) {
      this.endedReason = `truncated:max-steps(${this.opts.maxSteps})`;
    }

    return {
      action: name,
      actionIndex: idx,
      step: this.info.step,
      counters: after,
      delta: {
        kills: after.kills - before.kills,
        deaths: after.deaths - before.deaths,
        questsCompleted: after.questsCompleted - before.questsCompleted,
        xpGained: after.xpGained - before.xpGained,
        levelUps: after.levelUps - before.levelUps,
        questProgress: after.questProgress - before.questProgress,
        lootCopper: after.lootCopper - before.lootCopper,
      },
      terminated: reply.terminated,
      truncated: reply.truncated,
    };
  }

  get counters(): Counters {
    return {
      kills: this.info.kills,
      deaths: this.info.deaths,
      questsCompleted: this.info.quests_done,
      // Прокси из НАБЛЮДЕНИЯ: сумма долей выполнения квестов ×100. Абсолютное
      // значение смысла не имеет, монотонность — имеет, а политике нужны только
      // сравнения «стало больше» (см. capabilities.questObjectiveCounts=false).
      questProgress: this.decoded.quests.reduce((acc, q) => acc + Math.round(q.progress * 100), 0),
      xpGained: this.info.xp,
      levelUps: Math.max(0, this.info.level - this.startLevel),
      // Мир не отдаёт накопленный урон: 0, а не выдуманное число. Ветка политики,
      // которая на него смотрит, при damageCounters=false просто не срабатывает.
      damageDealt: 0,
      damageTaken: 0,
      lootCopper: this.info.copper,
    };
  }

  observe(): WorldModel {
    const d = this.decoded;
    const maxHp = this.lastMaxHp || 1;
    const player: PlayerView = {
      hp: this.info.hp,
      maxHp,
      // По проводу ресурс — доля: храним долю и maxResource=1, чтобы отношение
      // hp/maxHp-подобные проверки политики оставались осмысленными.
      resource: d.resourceFrac,
      maxResource: 1,
      resourceType: 'observed-fraction',
      level: this.info.level,
      xp: this.info.xp,
      x: d.x,
      z: d.z,
      facing: d.facing,
      dead: d.dead,
      inCombat: d.inCombat,
      autoAttack: d.autoAttack,
      resting: d.resting,
      playerClass: this.opts.playerClass,
      targetId: d.target.present ? ID_TARGET : null,
    };

    const nearby: EntityView[] = d.mobs.map((m, k) =>
      this.entityFromBearing({
        id: idMobSlot(k),
        kind: 'mob',
        templateId: '',
        name: `mob#${k + 1}`,
        level: this.info.level + m.levelDelta,
        hp: m.hpFrac,
        maxHp: 1,
        hostile: true,
        dead: false,
        lootable: false,
        aggroOnMe: m.aggroOnMe,
        dist: m.dist,
        bearing: m.bearing,
      }, player),
    );

    // Один слот «ближайшего взаимодействуемого» — труп, объект или NPC.
    const corpses: EntityView[] = [];
    const objects: EntityView[] = [];
    const npcs: EntityView[] = [];
    if (d.interactable.present && d.interactable.kind) {
      const pin = d.interactable.kind === 'npc' ? this.nearestPin(player.x, player.z, INTERACT_RANGE_YARDS) : null;
      const view = this.entityFromBearing({
        id: ID_INTERACTABLE,
        // В модели мира сущности — mob/npc/object/player; «труп» — это мёртвый
        // lootable-моб (как и у стенда), а не отдельный вид.
        kind: d.interactable.kind === 'corpse' ? 'mob' : d.interactable.kind,
        templateId: pin?.templateId ?? '',
        name: pin?.name ?? `${d.interactable.kind}#1`,
        level: this.info.level,
        hp: 1,
        maxHp: 1,
        hostile: false,
        dead: d.interactable.kind === 'corpse',
        lootable: d.interactable.kind === 'corpse',
        aggroOnMe: false,
        dist: d.interactable.dist,
        bearing: d.interactable.bearing,
        questIds: pin?.questIds ?? [],
      }, player);
      if (d.interactable.kind === 'corpse') corpses.push(view);
      else if (d.interactable.kind === 'object') objects.push(view);
      else npcs.push(view);
    }

    const target: EntityView | null = d.target.present
      ? this.entityFromBearing({
          id: ID_TARGET,
          kind: 'mob',
          templateId: '',
          name: 'target',
          level: this.info.level + d.target.levelDelta,
          hp: d.target.hpFrac,
          maxHp: 1,
          hostile: d.target.hostile,
          dead: d.target.lootable,
          lootable: d.target.lootable,
          aggroOnMe: d.target.aggroOnMe,
          dist: d.target.dist,
          bearing: d.target.bearing,
        }, player)
      : null;

    const quests = this.questViews();
    return {
      step: this.info.step,
      // sim.time по проводу не отдаётся: восстанавливаем из шагов и frameSkip
      // (20 тиков = 1 сек мира, DT — из данных игры).
      time: this.info.step * this.opts.frameSkip * TICK_SECONDS,
      player,
      target,
      nearby,
      npcs,
      objects,
      corpses,
      mapPins: this.mapPins(quests, player),
      quests,
      counters: this.counters,
      copper: this.info.copper,
    };
  }

  /** Готовность — из obs (её считает сама игра), а имена слотов — из того же
   *  источника, которым игра заполняет sim.known (abilitiesKnownAt), поэтому
   *  нумерация слотов совпадает со стендом один в один. */
  abilities(): AbilityView[] {
    const done = new Set(this.decoded.quests.filter((q) => q.state === 'done').map((q) => q.id));
    const known = knownAbilities(this.opts.playerClass, this.info.level, done);
    return this.decoded.abilities.map((a) => ({
      slot: a.slot,
      id: known[a.slot] ?? `slot_${a.slot + 1}`,
      ready: a.ready,
      cooldownFrac: a.cooldownFrac,
    }));
  }

  countItem(_itemId: string): number {
    if (!this.capabilities.itemCountApi) {
      throw new Error(
        'мир за бриджем не отдаёт содержимое сумок (itemCountApi=false) — молчаливого 0 не будет; ' +
          'лут проверяется счётчиками мира (copper/quests_done) и долей выполнения квеста',
      );
    }
    return 0;
  }

  questState(questId: string): string {
    const found = this.decoded.quests.find((q) => q.id === questId);
    if (!found) throw new Error(`в наблюдении мира нет квеста "${questId}"`);
    // 'observed': active/ready/done различимы точно, а ноль неразличим между
    // available и none/failed — возвращаем 'other' и НЕ угадываем доступность.
    return found.state;
  }

  close(): void {
    this.client.close();
  }

  // --- вспомогательное ---------------------------------------------------------

  /** Абсолютная позиция сущности из дистанции и пеленга: в игре угол — atan2(dx, dz),
   *  а obs кодирует rel = normAngle(angleTo(player, entity) - facing). */
  private entityFromBearing(
    base: Omit<EntityView, 'x' | 'z' | 'questIds' | 'availableQuests' | 'completableQuests'> & { questIds?: string[] },
    player: PlayerView,
  ): EntityView {
    const abs = player.facing + base.bearing;
    const questIds = base.questIds ?? [];
    const stateOf = (qid: string) => this.questStateSafe(qid);
    // По проводу 'available' неразличимо (ноль = available ИЛИ none/failed),
    // поэтому predictedUsefulAccept здесь неприменим: он требовал бы угадать.
    // Вместо угадывания — кандидаты: проходимые квесты этого NPC, которые не
    // 'done' и не 'active'. Факт выдачи проверяет FSM (ACCEPT → VERIFY_ACCEPT):
    // interact и сверка с наблюдением, а не догадка.
    const candidates = base.templateId
      ? questIds
          .filter((qid) => {
            const st = stateOf(qid);
            return st !== 'done' && st !== 'active' && isQuestCompletable(qid);
          })
          .sort((a, b) => questPriority(a) - questPriority(b))
      : [];
    return {
      ...base,
      questIds,
      availableQuests: candidates,
      completableQuests: candidates,
      x: player.x + base.dist * Math.sin(abs),
      z: player.z + base.dist * Math.cos(abs),
    };
  }

  /** questState без исключения — для внутренних проверок (состояние 'other' = неразличимо). */
  private questStateSafe(qid: string): string {
    return this.decoded.quests.find((q) => q.id === qid)?.state ?? 'other';
  }

  private nearestPin(x: number, z: number, radius: number): PinRecord | null {
    let best: PinRecord | null = null;
    let bestD = radius;
    for (const p of this.pins) {
      const d = Math.hypot(p.x - x, p.z - z);
      if (d <= bestD) {
        bestD = d;
        best = p;
      }
    }
    return best;
  }

  private questViews(): QuestView[] {
    const out: QuestView[] = [];
    for (const q of this.decoded.quests) {
      if (q.state === 'other') continue; // недоступные/не начатые по проводу неразличимы
      const def = questDef(q.id);
      if (!def) continue;
      const authored = (def.objectives ?? []) as Array<{
        type: string;
        targetMobId?: string;
        targetNpcId?: string;
        itemId?: string;
        targetObjectItemId?: string;
        count?: number;
        required?: number;
        label?: string;
      }>;
      const requiredTotal = authored.reduce((a, o) => a + (o.count ?? o.required ?? 1), 0);
      const objectives: ObjectiveView[] = authored.map((o) => {
        const required = o.count ?? o.required ?? 1;
        // Точный вывод возможен только для единственной цели: тогда наблюдаемая
        // доля относится целиком к ней. Иначе ставим 0 — консервативно «нужно всё»,
        // а не выдуманное число (questObjectiveCounts=false объявлен в capabilities).
        const have = authored.length === 1 ? Math.max(0, Math.min(required, Math.round(q.progress * required))) : 0;
        return {
          type: o.type,
          targetMobId: o.targetMobId,
          targetNpcId: o.targetNpcId,
          itemId: o.itemId,
          targetObjectItemId: o.targetObjectItemId,
          required,
          have,
          label: o.label,
        };
      });
      out.push({
        id: q.id,
        name: def.name ?? q.id,
        state: q.state as QuestStateName,
        objectives,
        progress: Math.round(q.progress * requiredTotal),
        required: requiredTotal,
        giverNpcId: def.giverNpcId,
        turnInNpcId: def.turnInNpcId,
      });
    }
    // Ближайшие к завершению — первыми (тот же принцип приоритета, что и у стенда).
    out.sort((a, b) => questPriority(a.id) - questPriority(b.id) || b.progress - a.progress);
    return out;
  }

  /** Слой карты: статические пины NPC из контент-данных игры + точки сдачи активных квестов.
   *  Это знание клиента (карта и журнал), а не наблюдение: мир реплицирует сущности
   *  только в радиусе интереса, а NPC по проводу виден лишь в INTERACT_RANGE. */
  private mapPins(quests: QuestView[], player: PlayerView): MapPin[] {
    const pins: MapPin[] = [];
    const dist = (x: number, z: number) => Math.hypot(x - player.x, z - player.z);
    const active = new Map(quests.map((q) => [q.id, q]));

    for (const p of this.pins) {
      for (const qid of p.questIds) {
        const seen = active.get(qid);
        if (seen?.state === 'done') continue;
        // Консервативно: по проводу 'other' неразличимо между available и none,
        // поэтому пин помечен giver'ом, а факт выдачи проверяется interact'ом.
        const kind: MapPin['kind'] = seen && seen.turnInNpcId === p.templateId ? 'turnin' : 'giver';
        pins.push({ templateId: p.templateId, name: p.name, x: p.x, z: p.z, kind, questId: qid, dist: dist(p.x, p.z) });
      }
    }
    for (const q of quests) {
      if (!q.turnInNpcId || q.state === 'done') continue;
      const pin = this.pins.find((p) => p.templateId === q.turnInNpcId);
      if (!pin) continue;
      pins.push({
        templateId: pin.templateId,
        name: pin.name,
        x: pin.x,
        z: pin.z,
        kind: 'turnin',
        questId: q.id,
        dist: dist(pin.x, pin.z),
      });
    }
    return pins;
  }

  /** Диапазон боевой видимости мира (RL-obs: 60 ярдов) — для единообразия отчётов. */
  get viewRadius(): number {
    return VIEW_RADIUS;
  }
}

/** Порядок квестов игры (для диагностики: что мир вообще знает о квестах). */
export const BRIDGE_QUEST_ORDER = questOrder;
