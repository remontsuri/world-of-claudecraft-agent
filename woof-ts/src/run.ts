/**
 * run.ts — точка входа: живой прогон агента против настоящей симуляции игры.
 *
 *   node dist/run.mjs --seed 42 --class warrior --steps 400
 *
 * Всё, что нужно машине: node 20+ и ссылка game -> чекаут World of ClaudeCraft
 * (создаёт tools/setup_game.sh). Ни браузера, ни CDP, ни HTTP-моста, ни GPU.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { NdjsonBridge } from './bridge/ndjson_bridge';
import { execFileSync } from 'node:child_process';
import { buildAgent, unsupportedReasons } from './core/build';
import { gameFacts, classAbilities, INTERACT_RANGE_YARDS, INTEREST_DROP_RADIUS } from './facts';
import { CANON, COMPOSITES } from './skills/canon';
import { diffFromDefaults, PARAMS, PARAM_SPECS } from './policy/params';
import { SimWorld } from './world/sim_world';
import { describeCapabilities, type World } from './world/world';
import {
  objectiveTypeCounts,
  SUPPORTED_OBJECTIVE_TYPES,
  UNSUPPORTED_OBJECTIVE_TYPES,
} from './world/quest_policy';
import { VIEW_RADIUS } from './world/types';

type Transport = 'sim' | 'ndjson';

interface CliOptions {
  /** sim — мир в нашем процессе (SimWorld); ndjson — headless env server игры за бриджем. */
  transport: Transport;
  /** Путь к собранному env-серверу (tools/build_env.sh); null = dist-env/env_server.cjs. */
  envServer: string | null;
  seed: number;
  playerClass: string;
  playerLevel: number;
  steps: number;
  frameSkip: number;
  npcView: number;
  worldSteps: number;
  quiet: boolean;
  every: boolean;
  json: string | null;
}

function parseArgs(argv: string[]): CliOptions {
  const o: CliOptions = {
    transport: 'sim' as Transport,
    envServer: null,
    seed: 42,
    playerClass: 'warrior',
    playerLevel: 1,
    steps: 0,
    frameSkip: 5,
    npcView: VIEW_RADIUS,
    worldSteps: 0,
    quiet: false,
    every: false,
    json: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case '--transport': o.transport = argv[++i] as Transport; break;
      case '--env-server': o.envServer = argv[++i]; break;
      case '--seed': o.seed = Number(argv[++i]); break;
      case '--class': o.playerClass = argv[++i]; break;
      case '--level': o.playerLevel = Number(argv[++i]); break;
      case '--steps': o.steps = Number(argv[++i]); break;
      case '--frame-skip': o.frameSkip = Number(argv[++i]); break;
      case '--npc-view': o.npcView = Number(argv[++i]); break;
      case '--world-steps': o.worldSteps = Number(argv[++i]); break;
      case '--quiet': o.quiet = true; break;
      case '--every': o.every = true; break;
      case '--json': o.json = argv[++i]; break;
      case '--help':
      case '-h':
        console.log(
          [
            'Использование: node dist/run.mjs [опции]',
            '  --transport T   sim (мир в нашем процессе) | ndjson (headless env server игры за бриджем)',
            '  --env-server P  путь к env-серверу (по умолчанию dist-env/env_server.cjs; сборка: tools/build_env.sh)',
            '  --seed N        сид мира (по умолчанию 42); мир воспроизводим от сида',
            '  --class NAME    класс игрока (warrior, mage, ... — см. факты игры)',
            '  --level N       стартовый уровень (1..max_level)',
            '  --steps N       бюджет решений агента (0 = до конца эпизода)',
            '  --frame-skip N  тиков мира на одно решение (по умолчанию 5, как у upstream)',
            '  --npc-view N    радиус видимости NPC как живых сущностей (по умолчанию 60 — как все',
            '                  остальные; 0 = ПРИВИЛЕГИЯ СТЕНДА: NPC видны на всю карту, в живом мире так нельзя)',
            '  --world-steps N лимит тиков мира (0 = без лимита; у upstream по умолчанию 8000 на эпизод)',
            '  WOOF_PARAMS=f.json  переопределить пороги агента (список и диапазоны: src/policy/params.ts)',
            '  --quiet         без построчного журнала, только вехи и SUMMARY',
            '  --every         печатать каждое решение (диагностика)',
            '  --json PATH     куда положить доказательства прогона (JSON)',
          ].join('\n'),
        );
        process.exit(0);
        break;
      default:
        if (a.startsWith('--')) {
          console.error(`[WoOF] неизвестная опция "${a}" (--help)`);
          process.exit(2);
        }
    }
  }
  if (!Number.isFinite(o.seed) || !Number.isFinite(o.steps) || !Number.isFinite(o.frameSkip)) {
    console.error('[WoOF] --seed/--steps/--frame-skip обязаны быть числами');
    process.exit(2);
  }
  if (o.transport !== 'sim' && o.transport !== 'ndjson') {
    console.error(`[WoOF] неизвестный транспорт "${o.transport}"; доступно: sim, ndjson`);
    process.exit(2);
  }
  return o;
}

function gameVersion(): { version: string; commit: string | null } {
  let version = 'unknown';
  try {
    version = JSON.parse(readFileSync(new URL('../game/package.json', import.meta.url), 'utf8')).version;
  } catch (e) {
    version = `unknown (${(e as Error).message})`;
  }
  let commit: string | null = null;
  try {
    commit = execFileSync('git', ['-C', new URL('../game', import.meta.url).pathname, 'rev-parse', 'HEAD'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'], // не мусорим в stderr, если чекаут без .git
    }).trim();
  } catch {
    commit = null; // чекаут без .git — не ошибка, но и выдумывать нечего
  }
  return { version, commit };
}

export function main(argv: string[] = process.argv.slice(2)): number {
  const opts = parseArgs(argv);
  const facts = gameFacts();
  const game = gameVersion();

  console.log(
    `[WoOF] TS-агент: seed=${opts.seed} class=${opts.playerClass} level=${opts.playerLevel} ` +
      `steps=${opts.steps > 0 ? opts.steps : 'без ограничения'} frame_skip=${opts.frameSkip}`,
  );
  console.log(
    `[WoOF] игра: version=${game.version} commit=${game.commit ?? 'n/a'} obs=${facts.obsSize} ` +
      `actions=${facts.numActions} quests=${facts.questCount} max_level=${facts.maxLevel} ` +
      `melee=${facts.meleeRange} interact=${facts.interactRange}`,
  );

  // Политика наблюдения заявлена ДО прогона. Живой мир реплицирует сущности только
  // в радиусе интереса (PLAYER_INTEREST_DROP_RADIUS=100, headless env — throttle 80),
  // поэтому по умолчанию NPC для нас — такие же живые сущности, как мобы: видны в
  // VIEW_RADIUS=60 (совпадает с RL-obs игры, obs.ts: d < 60). Знание «где на карте
  // квестодатель» берётся отдельно, из статического контента игры (слой mapPins).
  console.log(
    `[WoOF] наблюдение: все живые сущности (мобы/трупы/объекты/NPC) = ${opts.npcView} ярдов ` +
      `(RL-obs игры: d < 60; радиус интереса живой игры=${INTEREST_DROP_RADIUS}, headless throttle=80)`,
  );
  if (opts.npcView <= 0) {
    console.log(
      '[WoOF] ВНИМАНИЕ: --npc-view 0 — ПРИВИЛЕГИЯ СТЕНДА (NPC видны на всю карту). ' +
        'В мире, сопоставимом с онлайн-игрой, так нельзя: результат с этим флагом не переносится.',
    );
  }
  console.log(
    '[WoOF] знание карты (контент-данные, не наблюдение): статические пины NPC (NPCS[*].pos/questIds), ' +
      'лагеря мобов (CAMPS), точки интереса зоны (pois)',
  );

  // Пороги агента объявлены ДО прогона: базовые значения и чем мы их переопределили.
  // Переопределение — только через WOOF_PARAMS=<file.json> (см. src/policy/params.ts):
  // так каждый прогон изолирован, а контур обучения гоняет кандидатов отдельными процессами.
  const pdiff = diffFromDefaults();
  console.log(
    `[WoOF] пороги: базовых ${PARAM_SPECS.length}, переопределено ${Object.keys(pdiff).length}` +
      (Object.keys(pdiff).length
        ? ' — ' + Object.entries(pdiff).map(([k, v]) => `${k}: ${v.from}→${v.to}`).join(', ')
        : ' (WOOF_PARAMS не задан)'),
  );

  // Политика квестов заявлена ДО прогона: какие типы целей проходимы и почему.
  // Числа — из данных игры (QUESTS), а не наша оценка.
  const objCounts = objectiveTypeCounts();
  const objTotal = Object.values(objCounts).reduce((a, b) => a + b, 0);
  console.log(
    `[WoOF] цели квестов в игре (${objTotal} шт.): ` +
      Object.entries(objCounts)
        .sort((a, b) => b[1] - a[1])
        .map(([t, n]) => `${t}=${n}`)
        .join(', '),
  );
  console.log(`[WoOF] политика квестов: берём только цели ${SUPPORTED_OBJECTIVE_TYPES.join('/')}; НЕ берём —`);
  for (const [t, why] of Object.entries(UNSUPPORTED_OBJECTIVE_TYPES)) console.log(`        ${t}: ${why}`);

  // Возможности заявлены ДО прогона (правило проекта: пороги — до измерения).
  const abilities = classAbilities(opts.playerClass);
  const reasons = unsupportedReasons(opts.playerClass);
  const unsupported = Object.keys(reasons);
  const supported = CANON.filter((s) => !reasons[s]);
  console.log(`[WoOF] навыки поддерживаются (${supported.length}): ${supported.join(', ')}`);
  console.log(`[WoOF] навыки НЕ поддерживаются (${unsupported.length}) — заявлено до прогона:`);
  for (const s of unsupported) console.log(`        ${s}: ${reasons[s]}`);
  console.log(`[WoOF] композиты исполнителя: ${COMPOSITES.join(', ')}`);
  console.log(`[WoOF] способности класса ${opts.playerClass} (порядок изучения = слоты ability_N): ${abilities.join(', ')}`);

  // Транспорт объявлен до прогона: политика одна и та же, а вот что мир показывает —
  // по-разному (см. capabilities и BRIDGE.md). Бридж — это отдельный процесс с
  // headless env server игры, собранным нашим esbuild (tools/build_env.sh).
  let world: World;
  if (opts.transport === 'ndjson') {
    const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
    const server = opts.envServer ?? join(projectRoot, 'dist-env/env_server.cjs');
    if (!existsSync(server)) {
      console.error(`[WoOF] нет env-сервера: ${server} — соберите: bash tools/build_env.sh`);
      return 2;
    }
    if (opts.npcView !== VIEW_RADIUS) {
      console.log('[WoOF] --npc-view игнорируется для транспорта ndjson: по проводу NPC виден только в INTERACT_RANGE');
    }
    console.log(`[WoOF] транспорт: ndjson-бридж к ${server}`);
    const bridge = new NdjsonBridge({
      seed: opts.seed,
      playerClass: opts.playerClass,
      playerLevel: opts.playerLevel,
      frameSkip: opts.frameSkip,
      maxSteps: opts.worldSteps,
      spec: { command: process.execPath, args: [server], cwd: projectRoot },
    });
    // Процесс мира не должен переживать прогон: закрываем и при исключении тоже.
    process.on('exit', () => bridge.close());
    world = bridge;
  } else {
    world = SimWorld.create({
      seed: opts.seed,
      playerClass: opts.playerClass,
      playerLevel: opts.playerLevel,
      frameSkip: opts.frameSkip,
      maxSteps: opts.worldSteps, // 0 = без лимита мира: эпизод ограничивают решения агента
      npcViewRadius: opts.npcView,
      gathererIdentity: { kind: 'headless', id: `hl:woof-ts:${opts.seed}` },
    });
  }

  // Возможности мира заявлены ДО прогона: целевой мир сопоставим с онлайн-игрой,
  // поэтому in-process Sim — только стенд, и всё привилегированное объявлено явно.
  for (const line of describeCapabilities(world.capabilities)) console.log(`[WoOF] мир: ${line}`);

  // Сборка агента вынесена в src/core/build.ts: тем же кодом агент собирается для
  // любого транспорта мира (in-process стенд, бридж к headless env upstream, позже
  // живой сервер) и у тестов появляется точка входа без спавна процесса.
  const { fsm, arbitration, executor, memory, library, agent } = buildAgent(world, {
    quiet: opts.quiet,
    logEvery: opts.every,
    interactRange: facts.interactRange,
    unsupportedSkills: unsupported,
  });

  const w0 = world.observe();
  console.log(
    `[WoOF] start: hp=${w0.player.hp}/${w0.player.maxHp} pos=(${w0.player.x.toFixed(1)}, ${w0.player.z.toFixed(1)}) ` +
      `lvl=${w0.player.level} phase=${fsm.phase} mobs=${w0.nearby.length} npcs=${w0.npcs.length} quests_visible=${w0.quests.length}`,
  );

  const summary = agent.run(opts.steps);

  const evidence = {
    generatedAt: new Date().toISOString(),
    line: 'woof-ts (TypeScript + headless src/sim)',
    game,
    facts,
    options: opts,
    worldCapabilities: world.capabilities,
    params: PARAMS,
    paramsDiff: pdiff,
    transport: {
      kind: opts.transport,
      envServer: opts.transport === 'ndjson' ? (opts.envServer ?? 'dist-env/env_server.cjs') : null,
      capabilities: world.capabilities,
      note:
        opts.transport === 'ndjson'
          ? 'мир за NDJSON-бриджем: нет id/вида сущностей, нет накопленного урона, состояние квеста available неразличимо (см. BRIDGE.md)'
          : 'in-process стенд: полный доступ к Sim (привилегии объявлены в capabilities)',
    },
    observationPolicy: {
      combatViewRadius: VIEW_RADIUS,
      // За бриджем NPC виден только в INTERACT_RANGE (один слот «ближайшего
      // взаимодействуемого» в obs) — это факт транспорта, а не настройка.
      npcViewRadius: opts.transport === 'ndjson' ? INTERACT_RANGE_YARDS : opts.npcView,
      interestDropRadius: INTEREST_DROP_RADIUS,
      headlessIdleThrottle: 80,
      mapKnowledge: 'статические пины NPC (NPCS[*].pos/questIds), лагеря мобов (CAMPS), pois зоны',
      note:
        opts.npcView <= 0
          ? 'ПРИВИЛЕГИЯ СТЕНДА: NPC видны на всю карту — в живом мире так нельзя'
          : 'живые сущности видны в одном радиусе; знание карты — из контент-данных',
    },
    questPolicy: {
      supportedObjectiveTypes: [...SUPPORTED_OBJECTIVE_TYPES],
      unsupportedObjectiveTypes: UNSUPPORTED_OBJECTIVE_TYPES,
      objectiveTypeCounts: objCounts,
      note: 'квест берём, только если игра выдаст проходимый; выбор NPC — по questPriority',
    },
    supportedSkills: supported,
    unsupportedSkills: reasons,
    start: {
      hp: w0.player.hp,
      maxHp: w0.player.maxHp,
      x: w0.player.x,
      z: w0.player.z,
      level: w0.player.level,
      mobsInView: w0.nearby.length,
      npcsInView: w0.npcs.length,
    },
    summary,
    finalCounters: world.counters,
    visitedCells: memory.visited.size,
    recentActions: memory.recentActions.slice(-40),
  };
  if (opts.json) {
    mkdirSync(dirname(opts.json), { recursive: true });
    writeFileSync(opts.json, JSON.stringify(evidence, null, 2));
    console.log(`[WoOF] доказательства: ${opts.json}`);
  }

  const ok = summary.kills >= 1;
  console.log(ok ? '[WoOF] ПРОГОН СОСТОЯЛСЯ: есть настоящие убийства' : '[WoOF] ВНИМАНИЕ: убийств нет — см. журнал');
  return ok ? 0 : 1;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  process.exit(main());
}
