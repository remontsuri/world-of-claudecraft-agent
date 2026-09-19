/**
 * cdp_probe.ts — зонд живой вкладки (задача C1.1).
 *
 * Что обязан доказать ДО любого прогона:
 *  1. Chrome с отладочным портом отвечает (`GET /json/list`);
 *  2. среди вкладок есть ЖИВАЯ страница в мире (`window.__game.sim.player.pos`),
 *     а не мёртвая вкладка с тем же URL — грабель замороженной линии;
 *  3. какие методы страницы реально существуют (`api`): без этого любое действие
 *     агента было бы выдумкой;
 *  4. что мир отдаёт: hp/pos/level, сущности, состояния квестов, живые позиции NPC,
 *     способности, инвентарь, и чего в нашей модели нет (unknownKinds).
 *
 * Зонд только читает: никаких applyAction, никакого ввода, никакой перезагрузки
 * страницы (Page.reload/Page.navigate запрещены в `cdp_client.ts` структурно).
 *
 * Запуск (на машине владельца, где живут браузер и игра):
 *   npm run build && node dist/cdp_probe.mjs [--cdp http://127.0.0.1:9222] [--url-hint 5173]
 */
import { acquireLivePage } from '../src/bridge/cdp_client';
import { BrowserWorld, BROWSER_UNSUPPORTED_OBJECTIVES, PAGE_API_CANDIDATES } from '../src/world/browser_world';
import { browserCompletable } from '../src/world/browser_world';
import { questOrder } from '../src/facts';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

interface Args {
  cdp: string;
  urlHint: string;
  targetId?: string;
  json?: string;
}

function parseArgs(argv: readonly string[]): Args {
  const out: Args = { cdp: 'http://127.0.0.1:9222', urlHint: '5173' };
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
    else if (a === '--json') out.json = next();
    else if (a === '--help' || a === '-h') throw new Error('HELP');
    else throw new Error(`ПРОВАЛ: неизвестный аргумент '${a}'`);
  }
  return out;
}

async function main(): Promise<number> {
  const args = parseArgs(process.argv.slice(2));
  console.log(`[зонд] Chrome CDP: ${args.cdp}, подсказка URL: '${args.urlHint}'`);
  const page = await acquireLivePage({ cdpBase: args.cdp, urlHint: args.urlHint, targetId: args.targetId });
  const detail = page.probe.detail ?? {};
  console.log(`[зонд] ЖИВАЯ вкладка: ${page.target.url} (${page.target.title || 'без заголовка'})`);
  console.log(`[зонд] id=${page.target.id}`);
  console.log(
    `[зонд] персонаж: hp=${detail.hp}/${detail.maxHp} lvl=${detail.level} класс=${detail.playerClass || '?'} ` +
      `pos=(${Number(detail.x).toFixed(1)}, ${Number(detail.z).toFixed(1)}) facing=${Number(detail.facing).toFixed(2)} ` +
      `dead=${detail.dead} inCombat=${detail.inCombat}`,
  );
  console.log(`[зонд] сущностей в мире: ${detail.entities}, primaryId=${detail.primaryId}, контроллер: ${detail.hasController ? (detail.controllerKeys as string[]).join(',') : 'НЕТ'}`);
  for (const p of page.probes) {
    if (!p.live) console.log(`[зонд] отклонена: ${p.url} — ${p.reason}`);
  }

  const world = new BrowserWorld({ evaluate: (expr) => page.session.evaluate(expr), log: (s) => console.log(s) });
  const w = await world.observe();
  console.log('[зонд] === объявление возможностей (ДО прогона) ===');
  for (const line of world.declare()) console.log(`[зонд] ${line}`);

  const api = world.pageApi;
  const present = PAGE_API_CANDIDATES.filter((c) => api[c] === 'function');
  const absent = PAGE_API_CANDIDATES.filter((c) => api[c] !== 'function');
  console.log(`[зонд] api страницы: есть ${present.length}/${PAGE_API_CANDIDATES.length} → ${present.join(', ')}`);
  if (absent.length) console.log(`[зонд] api страницы: НЕТ → ${absent.map((c) => `${c}=${api[c] ?? '?'}`).join(', ')}`);
  console.log(`[зонд] мир: nearby=${w.nearby.length} npcs=${w.npcs.length} objects=${w.objects.length} corpses=${w.corpses.length} pins=${w.mapPins.length}`);
  console.log(`[зонд] квесты в модели: ${w.quests.map((q) => `${q.id}=${q.state}`).join(', ') || '(ни одного)'}`);
  const states = world.lastSnapshot?.questStates ?? {};
  const available = Object.entries(states).filter(([, s]) => s === 'available').map(([q]) => q);
  console.log(`[зонд] доступно у игры: ${available.length} → ${available.join(', ') || '(нет)'}`);
  console.log(
    `[зонд] из доступных проходимы для нас: ${available.filter((q) => browserCompletable(q).ok).join(', ') || '(ни одного)'}`,
  );
  for (const q of available) {
    const c = browserCompletable(q);
    if (!c.ok) console.log(`[зонд]   не берём ${q}: ${c.reason}`);
  }
  console.log(`[зонд] не перенесено в браузерную линию: ${Object.keys(BROWSER_UNSUPPORTED_OBJECTIVES).join(', ')}`);
  console.log(`[зонд] способности: ${world.abilities().map((a) => `${a.id}${a.ready ? '' : ` (кд ${a.cooldownFrac.toFixed(2)})`}`).join(', ') || '(нет)'}`);
  console.log(`[зонд] инвентарь: ${world.lastSnapshot?.inventory.length ?? 0} слотов, сумки=${world.lastSnapshot?.bags}/${world.lastSnapshot?.bagCapacity}`);
  if (Object.keys(world.unknownKinds).length) {
    console.log(`[зонд] ВНИМАНИЕ: виды сущностей вне нашей модели: ${JSON.stringify(world.unknownKinds)}`);
  }
  const npcLive = Object.keys(world.lastSnapshot?.npcPositions ?? {});
  console.log(`[зонд] живые позиции NPC (авторитет для сдачи): ${npcLive.length} → ${npcLive.join(', ') || '(ни одного NPC не видно)'}`);
  if (npcLive.length === 0) {
    console.log('[зонд] ВНИМАНИЕ: NPC не видны в sim.entities — сдача квеста пойдёт по пинам из контента игры; это находка, а не норма');
  }
  console.log(`[зонд] квестов всего в контенте: ${questOrder.length}; задержка CDP ≈ ${world.capabilities.latencyMs} мс`);

  if (args.json) {
    const payload = {
      when: new Date().toISOString(),
      cdp: args.cdp,
      urlHint: args.urlHint,
      target: { id: page.target.id, url: page.target.url, title: page.target.title },
      probe: detail,
      rejected: page.probes.filter((p) => !p.live).map((p) => ({ url: p.url, reason: p.reason })),
      capabilities: world.capabilities,
      declaration: world.declare(),
      api,
      unknownKinds: world.unknownKinds,
      world: {
        player: w.player,
        counters: w.counters,
        copper: w.copper,
        nearby: w.nearby.length,
        npcs: w.npcs.map((n) => ({ id: n.id, templateId: n.templateId, dist: n.dist, questIds: n.questIds, available: n.availableQuests, completable: n.completableQuests })),
        quests: w.quests,
        mapPins: w.mapPins,
        abilities: world.abilities(),
        npcPositions: world.lastSnapshot?.npcPositions ?? {},
      },
    };
    mkdirSync(dirname(args.json), { recursive: true });
    writeFileSync(args.json, JSON.stringify(payload, null, 2));
    console.log(`[зонд] evidence: ${args.json}`);
  }

  page.session.close();
  console.log('[зонд] ГОТОВО: вкладка живая, мир читается, способности и api подтверждены');
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((e: Error) => {
    if (e.message === 'HELP') {
      console.log('использование: node dist/cdp_probe.mjs [--cdp URL] [--url-hint 5173] [--target-id ID] [--json path]');
      process.exit(0);
    }
    console.error(`[зонд] ${e.message}`);
    process.exit(1);
  });
