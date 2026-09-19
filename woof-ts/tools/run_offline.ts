/**
 * run_offline.ts — живой прогон агента в браузерном офлайн-мире (C1.6 = J8).
 *
 * Приёмка объявлена ДО измерения (правило проекта), порог тот же, что был
 * объявлен в замороженной линии для J8: `quests_done >= 1` И `kills >= 1`,
 * без правок политики под результат. Отчёт — в том же формате SUMMARY, чтобы
 * число можно было сравнить с полигоном Java-линии.
 *
 * Порядок на машине владельца:
 *   1) в дереве игры: pnpm install --frozen-lockfile && pnpm run dev   → :5173
 *   2) в браузере: http://localhost:5173 → «Play Offline» → войти в мир
 *   3) Chrome с отладочным портом (отдельный профиль, чтобы не трогать свой):
 *        chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp http://localhost:5173
 *   4) здесь: npm run build && node dist/cdp_probe.mjs        (зонд, C1.1)
 *   5) здесь: node dist/run_offline.mjs --steps 200 --json evidence/offline-browser/run.json
 *
 * Запрещено (правила линии, наследуются из AGENTS.md): перезагружать страницу
 * через CDP, перехватывать ввод человека, запускать игру, если владелец уже в ней,
 * перезапускать мост/агента после правок без явной команды.
 */
import { acquireLivePage } from '../src/bridge/cdp_client';
import { BrowserWorld, COUNTERS_PROVENANCE } from '../src/world/browser_world';
import { buildBrowserAgent } from '../src/core/browser_agent';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

interface Args {
  cdp: string;
  urlHint: string;
  targetId?: string;
  steps: number;
  maxMs: number;
  json?: string;
  quiet: boolean;
  logEvery: boolean;
  thresholdQuests: number;
  thresholdKills: number;
}

function parseArgs(argv: readonly string[]): Args {
  const out: Args = {
    cdp: 'http://127.0.0.1:9222',
    urlHint: '5173',
    steps: 200,
    maxMs: 0,
    quiet: false,
    logEvery: false,
    thresholdQuests: 1,
    thresholdKills: 1,
  };
  const num = (a: string, v: string | undefined): number => {
    if (v === undefined) throw new Error(`ПРОВАЛ: после ${a} нужно число`);
    const n = Number(v);
    if (!Number.isFinite(n)) throw new Error(`ПРОВАЛ: ${a} ждёт число, получено '${v}'`);
    return n;
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => {
      const v = argv[++i];
      if (v === undefined) throw new Error(`ПРОВАЛ: после ${a} нужен аргумент`);
      return v;
    };
    if (a === '--cdp') out.cdp = next();
    else if (a === '--url-hint') out.urlHint = next();
    else if (a === '--target-id') out.targetId = next();
    else if (a === '--steps') out.steps = num(a, next());
    else if (a === '--max-ms') out.maxMs = num(a, next());
    else if (a === '--json') out.json = next();
    else if (a === '--threshold-quests') out.thresholdQuests = num(a, next());
    else if (a === '--threshold-kills') out.thresholdKills = num(a, next());
    else if (a === '--quiet') out.quiet = true;
    else if (a === '--log-every') out.logEvery = true;
    else if (a === '--help' || a === '-h') throw new Error('HELP');
    else throw new Error(`ПРОВАЛ: неизвестный аргумент '${a}'`);
  }
  return out;
}

async function main(): Promise<number> {
  const args = parseArgs(process.argv.slice(2));
  const log = (s: string) => {
    if (!args.quiet) console.log(s);
  };

  // ПОРОГИ — до измерения, а не после.
  console.log('[прогон] ОБЪЯВЛЕНО ДО ИЗМЕРЕНИЯ:');
  console.log(`[прогон]   приёмка J8: quests_done >= ${args.thresholdQuests} И kills >= ${args.thresholdKills}`);
  console.log(`[прогон]   бюджет: steps=${args.steps}${args.maxMs ? `, max-ms=${args.maxMs}` : ''}, правки политики под результат запрещены`);
  console.log(`[прогон]   среда: офлайн-dev (привилегированная, devCommands включены) — результат НЕ объявляется применимым к честной игре`);
  console.log(`[прогон]   счётчики: kills — ${COUNTERS_PROVENANCE.kills}`);
  console.log(`[прогон]             deaths — ${COUNTERS_PROVENANCE.deaths}`);
  console.log(`[прогон]             quests_done — ${COUNTERS_PROVENANCE.questsCompleted}`);

  const page = await acquireLivePage({ cdpBase: args.cdp, urlHint: args.urlHint, targetId: args.targetId });
  console.log(`[прогон] живая вкладка: ${page.target.url} (id=${page.target.id})`);
  for (const p of page.probes) if (!p.live) console.log(`[прогон] отклонена вкладка: ${p.url} — ${p.reason}`);

  const world = new BrowserWorld({ evaluate: (expr) => page.session.evaluate(expr), log });
  const first = await world.observe();
  console.log('[прогон] === возможности мира (до прогона) ===');
  for (const line of world.declare()) console.log(`[прогон] ${line}`);
  console.log(
    `[прогон] старт: hp=${first.player.hp}/${first.player.maxHp} lvl=${first.player.level} ` +
      `pos=(${first.player.x.toFixed(1)}, ${first.player.z.toFixed(1)}) nearby=${first.nearby.length} npcs=${first.npcs.length} pins=${first.mapPins.length}`,
  );

  const agent = buildBrowserAgent(world, {
    log,
    verbose: true,
    logEvery: args.logEvery,
    navMaxTicks: 80,
    maxMs: args.maxMs,
  });
  const summary = await agent.run(args.steps);

  console.log(
    `[Agent] SUMMARY steps=${summary.steps} kills=${summary.kills} deaths=${summary.deaths} ` +
      `quests_done=${summary.questsDone} first_turn_in_step=${summary.firstTurnInStep} ` +
      `level=${summary.level} levelUps=${summary.levelUps} ended=${summary.ended} ms=${summary.ms}`,
  );
  for (const t of summary.turnIns) console.log(`[Agent] TURN_IN step=${t.step} quest=${t.questId} npc=${t.npc}`);
  if (summary.missingApi.length) console.log(`[Agent] ВНИМАНИЕ: нет методов страницы → ${summary.missingApi.join(', ')}`);
  if (Object.keys(summary.unknownKinds).length) console.log(`[Agent] ВНИМАНИЕ: виды сущностей вне модели → ${JSON.stringify(summary.unknownKinds)}`);

  const okQuests = summary.questsDone >= args.thresholdQuests;
  const okKills = summary.kills >= args.thresholdKills;
  const verdict = okQuests && okKills ? 'ПРИЁМКА J8 ПРОЙДЕНА' : 'ПРИЁМКА J8 НЕ ПРОЙДЕНА';
  console.log(`[прогон] ${verdict}: quests_done=${summary.questsDone} (порог ${args.thresholdQuests}), kills=${summary.kills} (порог ${args.thresholdKills})`);

  if (args.json) {
    const payload = {
      when: new Date().toISOString(),
      acceptance: {
        declaredBeforeRun: true,
        thresholds: { questsDone: args.thresholdQuests, kills: args.thresholdKills },
        passed: okQuests && okKills,
        verdict,
      },
      target: { id: page.target.id, url: page.target.url, title: page.target.title },
      rejectedTabs: page.probes.filter((p) => !p.live).map((p) => ({ url: p.url, reason: p.reason })),
      capabilities: world.capabilities,
      declaration: world.declare(),
      countersProvenance: COUNTERS_PROVENANCE,
      pageApi: world.pageApi,
      unknownKinds: summary.unknownKinds,
      summary,
      lastObservation: world.lastObservation,
    };
    mkdirSync(dirname(args.json), { recursive: true });
    writeFileSync(args.json, JSON.stringify(payload, null, 2));
    console.log(`[прогон] evidence: ${args.json}`);
  }

  page.session.close();
  return okQuests && okKills ? 0 : 1;
}

main()
  .then((code) => process.exit(code))
  .catch((e: Error) => {
    if (e.message === 'HELP') {
      console.log(
        'использование: node dist/run_offline.mjs [--cdp URL] [--url-hint 5173] [--target-id ID] ' +
          '[--steps N] [--max-ms N] [--json path] [--quiet] [--log-every] [--threshold-quests N] [--threshold-kills N]',
      );
      process.exit(0);
    }
    console.error(`[прогон] ${e.message}`);
    process.exit(1);
  });
