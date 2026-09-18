/**
 * tune.ts — контур самоулучшения: подбор порогов из объявленной таблицы.
 *
 *   node dist/tune.mjs --steps 150 --train-seeds 42,43 --val-seeds 44 --groups combat,survival
 *
 * Как устроено и почему именно так:
 *   1. Целевая функция объявлена ДО измерения (src/learn/objective.ts) и
 *      печатается в первых строках отчёта — правило проекта, а не формальность.
 *   2. Каждый кандидат прогоняется ОТДЕЛЬНЫМ ПРОЦЕССОМ: PARAMS читается при
 *      импорте модуля (статические импорты ESM поднимаются до разбора argv),
 *      поэтому переопределить пороги внутри процесса нельзя — только через
 *      WOOF_PARAMS=<file> в окружении дочернего процесса. Побочный плюс: падение
 *      кандидата не роняет тюнинг.
 *   3. Поиск — покоординатный спуск по объявленной сетке (def ± step, ± 2·step,
 *      в пределах [min, max]): значения вне сетки loadParams отвергает, поэтому
 *      «случайный поиск по непрерывному диапазону» здесь невозможен в принципе.
 *   4. Улучшение принимается только если средний скор на TRAIN-сидах вырос;
 *      финальный набор проверяется на VAL-сидах, которые в подборе не участвуют.
 *      Один сид — не результат (сид 7 в этой линии хрупок: 1 убийство, 183 смерти),
 *      поэтому сплит обязателен и пересечение сидов — исключение.
 *   5. Каждое измерение пишется в learning/history.jsonl (append-only): история
 *      не переписывается, отказ от гипотезы виден так же, как принятие.
 */
import { spawnSync } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { DEFAULT_PARAMS, PARAM_SPECS, diffFromDefaults, loadParams, type Params } from '../policy/params';
import { aggregate, describeObjective, score, seedSplit, type RunMetrics } from './objective';

const HERE = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(HERE, '..');

export interface TuneOptions {
  steps: number;
  rounds: number;
  trainSeeds: number[];
  valSeeds: number[];
  groups: string[];
  transport: 'sim' | 'ndjson';
  /** Сколько значений пробовать на параметр (1 = ±step, 2 = ±step и ±2·step). */
  candidatesPerParam: number;
  /** Секунды на весь тюнинг: по исчерпании останавливаемся и фиксируем лучшее. */
  budgetSeconds: number;
  outDir: string;
  /** Насколько должен вырасти средний скор, чтобы считать улучшение настоящим. */
  minDelta: number;
}

export interface SeedRun {
  seed: number;
  ok: boolean;
  metrics: RunMetrics | null;
  score: number;
  elapsedMs: number;
  error: string | null;
  evidence: string | null;
}

export interface Evaluation {
  params: Params;
  diff: Record<string, { from: number; to: number }>;
  runs: SeedRun[];
  mean: number;
  min: number;
  max: number;
}

const EVIDENCE_DIR = join(PROJECT_ROOT, 'evidence', 'tuning');

function parseList(raw: string | undefined, fallback: number[]): number[] {
  if (!raw) return fallback;
  const out = raw.split(',').map((s) => Number(s.trim())).filter((n) => Number.isFinite(n));
  if (out.length === 0) throw new Error(`пустой список чисел: "${raw}"`);
  return out;
}

export function parseTuneArgs(argv: string[]): TuneOptions {
  const o: TuneOptions = {
    steps: 150,
    rounds: 1,
    trainSeeds: [42],
    valSeeds: [44],
    groups: [],
    transport: 'sim',
    candidatesPerParam: 1,
    budgetSeconds: 1800,
    outDir: join(PROJECT_ROOT, 'learning'),
    // Порог принятия: 0 принимал шум (наблюдали принятие с приростом +0.05).
    // 1.0 пункта скора — меньше, чем вес одного убийства (5), но больше дрожания прогонов.
    minDelta: 1.0,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case '--steps': o.steps = Number(argv[++i]); break;
      case '--rounds': o.rounds = Number(argv[++i]); break;
      case '--train-seeds': o.trainSeeds = parseList(argv[++i], o.trainSeeds); break;
      case '--val-seeds': o.valSeeds = parseList(argv[++i], o.valSeeds); break;
      case '--groups': o.groups = String(argv[++i]).split(',').map((s) => s.trim()).filter(Boolean); break;
      case '--transport': o.transport = argv[++i] as TuneOptions['transport']; break;
      case '--candidates-per-param': o.candidatesPerParam = Number(argv[++i]); break;
      case '--budget-seconds': o.budgetSeconds = Number(argv[++i]); break;
      case '--out': o.outDir = resolve(String(argv[++i])); break;
      case '--min-delta': o.minDelta = Number(argv[++i]); break;
      case '--help':
      case '-h':
        console.log(
          [
            'Использование: node dist/tune.mjs [опции]',
            '  --steps N               бюджет решений агента в одном прогоне (по умолчанию 150)',
            '  --rounds N              сколько проходов по таблице порогов (по умолчанию 1)',
            '  --train-seeds 42,43     сиды подбора (обязательно не пересекаются с val)',
            '  --val-seeds 44          сиды проверки: на них подбор не смотрит',
            '  --groups combat,quest   группы порогов из PARAM_SPECS (пусто = все)',
            '  --transport sim|ndjson  мир: in-process стенд или headless env за бриджем',
            '  --candidates-per-param N  1 = def±step, 2 = def±step и def±2·step',
            '  --budget-seconds N      общий бюджет: по исчерпании фиксируем лучшее',
            '  --min-delta X           минимальный прирост среднего скора для принятия',
            '  --out DIR               каталог learning/ (history.jsonl, best.json, last_report.md)',
          ].join('\n'),
        );
        process.exit(0);
        break;
      default:
        if (a.startsWith('--')) {
          console.error(`[tune] неизвестная опция "${a}" (--help)`);
          process.exit(2);
        }
    }
  }
  return o;
}

/** Кандидатные значения параметра: сетка из объявленного шага, в пределах диапазона. */
export function candidateValues(key: string, current: number, perParam: number): number[] {
  const spec = PARAM_SPECS.find((s) => s.key === key);
  if (!spec) throw new Error(`нет такого параметра в PARAM_SPECS: ${key}`);
  const out: number[] = [];
  for (let k = 1; k <= perParam; k++) {
    for (const sign of [-1, 1]) {
      const v = Number((current + sign * k * spec.step).toFixed(6));
      if (v >= spec.min && v <= spec.max && v !== current && !out.includes(v)) out.push(v);
    }
  }
  return out;
}

/** Прогнать кандидата отдельным процессом: только так PARAMS действительно меняется. */
export function runCandidate(
  params: Params,
  seed: number,
  opts: TuneOptions,
  tag: string,
): SeedRun {
  mkdirSync(EVIDENCE_DIR, { recursive: true });
  const paramsFile = join(EVIDENCE_DIR, `params-${tag}.json`);
  const evidenceFile = join(EVIDENCE_DIR, `evidence-${tag}.json`);
  writeFileSync(paramsFile, JSON.stringify({ params }, null, 2));
  // Проверяем кандидата тем же строгим загрузчиком, которым пользуется прогон:
  // значение вне сетки/диапазона должно упасть здесь, а не «где-то в процессе».
  loadParams(paramsFile);

  const runScript = join(PROJECT_ROOT, 'dist', 'run.mjs');
  if (!existsSync(runScript)) {
    return { seed, ok: false, metrics: null, score: 0, elapsedMs: 0, error: `нет ${runScript}: npm run build`, evidence: null };
  }
  const args = [runScript, '--seed', String(seed), '--steps', String(opts.steps), '--quiet', '--json', evidenceFile];
  if (opts.transport === 'ndjson') args.push('--transport', 'ndjson');

  const t0 = Date.now();
  const proc = spawnSync(process.execPath, args, {
    cwd: PROJECT_ROOT,
    encoding: 'utf8',
    env: { ...process.env, WOOF_PARAMS: paramsFile },
    timeout: Math.max(60_000, opts.steps * 2_000),
  });
  const elapsedMs = Date.now() - t0;

  if (proc.error) {
    return { seed, ok: false, metrics: null, score: 0, elapsedMs, error: proc.error.message, evidence: null };
  }
  if (!existsSync(evidenceFile)) {
    const tail = (proc.stderr || proc.stdout || '').split('\n').filter(Boolean).slice(-3).join(' | ');
    return {
      seed,
      ok: false,
      metrics: null,
      score: 0,
      elapsedMs,
      // exit code 1 у run.mjs означает «прогон состоялся, но убийств нет» — это
      // валидный результат, а не ошибка; ошибкой считаем отсутствие доказательств.
      error: `нет evidence (exit=${proc.status}): ${tail}`,
      evidence: null,
    };
  }
  const ev = JSON.parse(readFileSync(evidenceFile, 'utf8')) as {
    summary: {
      steps: number;
      worldSteps: number;
      kills: number;
      deaths: number;
      questsDone: number;
      firstTurnInStep: number;
      level: number;
      xp: number;
      copper: number;
    };
    paramsDiff: Record<string, { from: number; to: number }>;
  };
  const metrics: RunMetrics = {
    kills: ev.summary.kills,
    deaths: ev.summary.deaths,
    questsDone: ev.summary.questsDone,
    firstTurnInStep: ev.summary.firstTurnInStep,
    worldSteps: ev.summary.worldSteps,
    level: ev.summary.level,
    xp: ev.summary.xp,
    copper: ev.summary.copper,
    steps: ev.summary.steps,
  };
  return { seed, ok: true, metrics, score: score(metrics), elapsedMs, error: null, evidence: evidenceFile };
}

function evaluate(params: Params, seeds: number[], opts: TuneOptions, tag: string): Evaluation {
  const runs = seeds.map((seed, i) => runCandidate(params, seed, opts, `${tag}-s${seed}-${i}`));
  const scores = runs.filter((r) => r.ok).map((r) => r.score);
  const agg = aggregate(scores);
  return { params, diff: diffFromDefaults(params), runs, ...agg };
}

function logHistory(outDir: string, entry: Record<string, unknown>): void {
  mkdirSync(outDir, { recursive: true });
  appendFileSync(join(outDir, 'history.jsonl'), `${JSON.stringify(entry)}\n`);
}

export function main(argv: string[] = process.argv.slice(2)): number {
  const opts = parseTuneArgs(argv);
  const split = seedSplit(opts.trainSeeds, opts.valSeeds);
  mkdirSync(opts.outDir, { recursive: true });

  // Объявление ДО измерения: функция, сплит, сетка и оценка стоимости.
  const specs = PARAM_SPECS.filter((s) => opts.groups.length === 0 || opts.groups.includes(s.group));
  const perParam = specs.reduce((n, s) => n + candidateValues(s.key, DEFAULT_PARAMS[s.key], opts.candidatesPerParam).length, 0);
  const planned = perParam * opts.rounds * split.train.length;
  console.log('[tune] целевая функция (объявлена до измерения):');
  for (const line of describeObjective()) console.log(`[tune]   ${line}`);
  console.log(`[tune] транспорт=${opts.transport}, шаги=${opts.steps}, раундов=${opts.rounds}`);
  console.log(`[tune] train-сиды=[${split.train.join(', ')}], val-сиды=[${split.val.join(', ')}] (не пересекаются — проверка, а не подгонка)`);
  console.log(`[tune] параметров в работе: ${specs.length} (${opts.groups.length ? opts.groups.join('+') : 'все группы'}), значений на параметр: до ${opts.candidatesPerParam * 2}`);
  console.log(`[tune] план: ~${planned} прогонов; бюджет ${opts.budgetSeconds} с — по исчерпании фиксируем лучшее`);
  console.log(`[tune] базовые пороги: ${Object.keys(DEFAULT_PARAMS).length} шт., src/policy/params.ts`);
  console.log(`[tune] порог принятия: +${opts.minDelta} к среднему скору train (меньше — шум, не улучшение)`);

  // Предупреждения объявляются ДО измерения и пишутся в отчёт: узкий сплит не делает
  // подбор невозможным, но делает его результат статистически бессмысленным.
  const warnings: string[] = [];
  if (split.train.length < 2) warnings.push(`train-сидов ${split.train.length}: на одном сиде улучшение неотличимо от подгонки под конкретный эпизод`);
  if (split.val.length < 3) warnings.push(`val-сидов ${split.val.length}: минимум три — иначе проверка на переобучение измеряет шум`);
  if (opts.steps < 100) warnings.push(`бюджет ${opts.steps} решений: короткий прогон находит «осторожные» пороги, а не результативные (скор зависит от бюджета — см. LEARNING.md)`);
  for (const w of warnings) console.log(`[tune] ВНИМАНИЕ: ${w}`);

  const startedAt = Date.now();
  const deadline = startedAt + opts.budgetSeconds * 1000;
  const history: Array<Record<string, unknown>> = [];

  const baseline = evaluate(DEFAULT_PARAMS, split.train, opts, 'baseline');
  const baseEntry = {
    ts: new Date().toISOString(),
    kind: 'baseline',
    transport: opts.transport,
    steps: opts.steps,
    seeds: split.train,
    diff: baseline.diff,
    scores: baseline.runs.map((r) => ({ seed: r.seed, ok: r.ok, score: r.score, metrics: r.metrics })),
    trainMean: baseline.mean,
  };
  history.push(baseEntry);
  logHistory(opts.outDir, baseEntry);
  console.log(`[tune] базовый средний скор на train: ${baseline.mean.toFixed(2)} (прогонов: ${baseline.runs.length}, ${Math.round((Date.now() - startedAt) / 1000)} с)`);

  let best: Params = { ...DEFAULT_PARAMS };
  let bestMean = baseline.mean;
  let accepted = 0;
  let rejected = 0;
  let budgetHit = false;

  for (let round = 1; round <= opts.rounds && !budgetHit; round++) {
    for (const spec of specs) {
      if (Date.now() > deadline) {
        budgetHit = true;
        break;
      }
      for (const value of candidateValues(spec.key, best[spec.key], opts.candidatesPerParam)) {
        if (Date.now() > deadline) {
          budgetHit = true;
          break;
        }
        const cand: Params = { ...best, [spec.key]: value };
        const tag = `r${round}-${spec.key}-${value}`.replace(/[^\w.-]/g, '_');
        const ev = evaluate(cand, split.train, opts, tag);
        const better = ev.mean > bestMean + opts.minDelta;
        const entry = {
          ts: new Date().toISOString(),
          kind: 'candidate',
          round,
          param: spec.key,
          from: best[spec.key],
          to: value,
          transport: opts.transport,
          steps: opts.steps,
          seeds: split.train,
          scores: ev.runs.map((r) => ({ seed: r.seed, ok: r.ok, score: r.score, metrics: r.metrics, error: r.error })),
          trainMean: ev.mean,
          bestMeanBefore: bestMean,
          accepted: better,
          failedRuns: ev.runs.filter((r) => !r.ok).length,
        };
        history.push(entry);
        logHistory(opts.outDir, entry);
        if (better) {
          accepted++;
          best = cand;
          bestMean = ev.mean;
          console.log(`[tune] ПРИНЯТО ${spec.key}: ${entry.from} → ${value} (train ${ev.mean.toFixed(2)} > ${(entry.bestMeanBefore as number).toFixed(2)})`);
        } else {
          rejected++;
          const why = ev.runs.some((r) => !r.ok) ? 'есть упавшие прогоны' : `train ${ev.mean.toFixed(2)} ≤ ${bestMean.toFixed(2)}`;
          console.log(`[tune] отказ   ${spec.key} → ${value}: ${why}`);
        }
      }
    }
  }

  // Проверка на отложенных сидах: без неё «улучшение» может быть подгонкой.
  const valBest = split.val.length > 0 ? evaluate(best, split.val, opts, 'val-best') : null;
  const valBase = split.val.length > 0 ? evaluate(DEFAULT_PARAMS, split.val, opts, 'val-baseline') : null;

  const bestRecord = {
    generatedAt: new Date().toISOString(),
    objective: describeObjective(),
    transport: opts.transport,
    steps: opts.steps,
    trainSeeds: split.train,
    valSeeds: split.val,
    params: best,
    paramsDiff: diffFromDefaults(best),
    trainMean: bestMean,
    baselineTrainMean: baseline.mean,
    valMean: valBest?.mean ?? null,
    baselineValMean: valBase?.mean ?? null,
    accepted,
    rejected,
    distinctChanged: Object.keys(diffFromDefaults(best)).length,
    minDelta: opts.minDelta,
    warnings,
    budgetHit,
    elapsedSeconds: Math.round((Date.now() - startedAt) / 1000),
  };
  writeFileSync(join(opts.outDir, 'best.json'), JSON.stringify(bestRecord, null, 2));

  const report = [
    `# Отчёт тюнинга ${bestRecord.generatedAt}`,
    '',
    '## Целевая функция (объявлена до измерения)',
    ...describeObjective().map((l) => `- ${l}`),
    '',
    '## Условия',
    `- транспорт: \`${opts.transport}\`, бюджет решений: ${opts.steps}`,
    `- train-сиды: ${split.train.join(', ')}; val-сиды: ${split.val.join(', ')} (не пересекаются)`,
    `- параметров в работе: ${specs.length}; принято шагов: ${accepted}; отклонено: ${rejected}; отличий в итоговом наборе: ${Object.keys(bestRecord.paramsDiff).length} (один параметр мог приниматься несколько раз)${budgetHit ? '; бюджет исчерпан — зафиксировано лучшее на момент остановки' : ''}`,
    `- порог принятия: +${opts.minDelta} к среднему скору train`,
    `- длительность: ${bestRecord.elapsedSeconds} с`,
    '',
    '## Результат',
    `- базовый средний скор (train): **${baseline.mean.toFixed(2)}**`,
    `- лучший средний скор (train): **${bestMean.toFixed(2)}**`,
    `- базовый средний скор (val): ${valBase ? `**${valBase.mean.toFixed(2)}**` : 'не измерялся'}`,
    `- лучший средний скор (val): ${valBest ? `**${valBest.mean.toFixed(2)}**` : 'не измерялся'}`,
    '',
    ...(warnings.length > 0 ? ['', '## Предупреждения (объявлены до измерения)', ...warnings.map((w) => `- ВНИМАНИЕ: ${w}`)] : []),
    '',
    '## Вердикт',
    valBest && valBase
      ? valBest.mean < valBase.mean
        ? `- **ПЕРЕОБУЧЕНИЕ**: на val-сидах набор хуже базового (${valBest.mean.toFixed(2)} < ${valBase.mean.toFixed(2)}) — не применять без проверки человеком`
        : `- на val-сидах набор не хуже базового (${valBest.mean.toFixed(2)} против ${valBase.mean.toFixed(2)}) — можно применять с оговоркой про размер сплита`
      : '- val не измерялся: набор НЕ проверен на отложенных сидах, применять нельзя',
    '',
    '## Принятые пороги (отличия от базовых)',
    ...(Object.keys(bestRecord.paramsDiff).length === 0
      ? ['- изменений нет: базовые пороги не удалось улучшить в рамках бюджета']
      : Object.entries(bestRecord.paramsDiff).map(([k, v]) => `- \`${k}\`: ${v.from} → ${v.to}`)),
    '',
    '## Воспроизведение',
    '```bash',
    'bash tools/setup_game.sh && npm run build',
    opts.transport === 'ndjson' ? 'bash tools/build_env.sh' : '# (для ndjson нужен собранный env-сервер)',
    `WOOF_PARAMS=learning/best.json node dist/run.mjs --seed ${split.train[0]} --steps ${opts.steps}${opts.transport === 'ndjson' ? ' --transport ndjson' : ''}`,
    '```',
    'История всех измерений (включая отказы): `learning/history.jsonl`.',
    '',
  ].join('\n');
  writeFileSync(join(opts.outDir, 'last_report.md'), report);

  console.log(`[tune] готово: принято ${accepted}, отклонено ${rejected}, лучшее train=${bestMean.toFixed(2)}` +
    (valBest ? `, val=${valBest.mean.toFixed(2)} (база ${valBase?.mean.toFixed(2)})` : ''));
  console.log(`[tune] записано: ${join(opts.outDir, 'best.json')}, ${join(opts.outDir, 'history.jsonl')}, ${join(opts.outDir, 'last_report.md')}`);
  if (budgetHit) console.log('[tune] бюджет времени исчерпан — зафиксировано лучшее из проверенного (не optimal, а honest)');
  // Прогноз на val хуже базового = переобучение на train: говорим об этом прямо.
  if (valBest && valBase) {
    if (valBest.mean < valBase.mean) {
      console.log('[tune] ВНИМАНИЕ: на val-сидах лучший набор ХУЖЕ базового — это ПЕРЕОБУЧЕНИЕ, набор не применять без проверки');
    } else {
      console.log('[tune] val: набор не хуже базового — применять можно, но сплит узкий (см. предупреждения)');
    }
  } else {
    console.log('[tune] ВНИМАНИЕ: val не измерялся — набор не проверен на отложенных сидах');
  }
  return 0;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  process.exit(main());
}
