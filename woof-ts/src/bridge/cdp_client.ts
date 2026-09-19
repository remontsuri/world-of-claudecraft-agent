/**
 * CDP-клиент (Chrome DevTools Protocol) для мира игры В БРАУЗЕРЕ (задача C1).
 *
 * Зачем: офлайн-режим игры (`pnpm run dev` → http://localhost:5173 → «Play Offline») —
 * одиночный мир без аккаунта и без авторитета сервера (README игры, «Offline, in the dev
 * server»). Сервера и сокета там нет, поэтому WS-транспорт (A1) подключать не к чему:
 * мир живёт внутри страницы. Единственная честная связь с ним — CDP.
 *
 * Факты upstream v0.43.2 (всё проверено по дереву игры, не по памяти):
 *  - страница отдаёт отладочную поверхность `window.__game = { sim: world, world, renderer,
 *    input, hud, online, controller, perf, gamepad, music, MOBS, ... }` (src/main.ts:5048),
 *    заполняется при входе в мир; часть полей помечена «Debug surface only»;
 *  - канон наблюдения и действий — `src/sim/obs.ts`: `encodeObs(sim)`, `applyAction(sim, i)`,
 *    `obsSize()`, `ACTIONS`, `NUM_ACTIONS`. Файл не зависит ни от Node, ни от DOM
 *    (0 вхождений node:/process./document./window.), а `headless/env_server.ts` (293 строки)
 *    — лишь stdio-обёртка вокруг этих же функций. Значит в странице доступен ТОТ ЖЕ канон,
 *    что и за headless-бриджем: переписывать действия руками не нужно;
 *  - dev-сервер vite отдаёт исходники по URL (`base: '/'`, `server.port: 5173`), поэтому
 *    модуль импортируется в странице как `await import('/src/sim/obs.ts')`;
 *  - офлайн-конфиг ставит `devCommands: import.meta.env.DEV` (src/main.ts:5163-5170),
 *    то есть в dev-сервере читы ВКЛЮЧЕНЫ. Агент их не вызывает структурно: он действует
 *    только через `applyAction` с индексами канонического `ACTIONS`, а dev-команд в нём нет;
 *  - темп задаёт страница (`requestAnimationFrame`): мир идёт в реальном времени,
 *    frameSkip=0, детерминизма нет (в отличие от стенда и headless-бриджа).
 *
 * ПРАВИЛА (проверяются тестом, а не намерением):
 *  - страницу НЕ перезагружать и не перенаправлять: Page.reload/Page.navigate и всё, что
 *    закрывает вкладку или браузер, запрещены (FORBIDDEN_CDP_METHODS);
 *  - зонд только читает: никаких applyAction и записи в window.__game;
 *  - если целей несколько — не угадываем, а требуем явного --url-hint;
 *  - человек играет в этой же вкладке: бридж не перехватывает ввод и не трогает HUD.
 */
import { resolveSocketFactory, type SocketFactory, type SocketLike } from './ws_socket';

export interface CdpTarget {
  id: string;
  type: string;
  title: string;
  url: string;
  webSocketDebuggerUrl?: string;
}

export interface CdpFrame {
  id?: number;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code?: number; message?: string };
}

/** Методы, которые ломают игру человека. Их вызов — ПРОВАЛ, а не «аккуратно». */
export const FORBIDDEN_CDP_METHODS: readonly string[] = [
  'Page.navigate',
  'Page.reload',
  'Page.stopLoading',
  'Page.close',
  'Target.closeTarget',
  'Target.activateTarget',
  'Browser.close',
  'Input.dispatchKeyEvent',
  'Input.dispatchMouseEvent',
];

export function assertAllowedMethod(method: string): void {
  if (FORBIDDEN_CDP_METHODS.includes(method)) {
    throw new Error(
      `ПРОВАЛ: метод CDP '${method}' запрещён — он перезагружает страницу, закрывает вкладку ` +
        'или перехватывает ввод человека. В этой вкладке играет владелец: бридж только читает мир.',
    );
  }
}

/** Разбор кадра CDP. Не-JSON — ПРОВАЛ: молча пропущенный ответ повесит ожидание. */
export function parseCdpFrame(text: string): CdpFrame {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (e) {
    throw new Error(`ПРОВАЛ: кадр CDP не JSON (${(e as Error).message}): ${text.slice(0, 200)}`);
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`ПРОВАЛ: кадр CDP не объект: ${text.slice(0, 200)}`);
  }
  return value as CdpFrame;
}

/** Список вкладок Chrome: GET /json/list. */
export async function listTargets(
  httpBase: string,
  fetchImpl: typeof fetch = fetch,
): Promise<CdpTarget[]> {
  const url = `${httpBase.replace(/\/$/, '')}/json/list`;
  let res: Response;
  try {
    res = await fetchImpl(url);
  } catch (e) {
    throw new Error(
      `ПРОВАЛ: Chrome не отвечает на ${url} (${(e as Error).message}).\n` +
        'Chrome должен быть запущен с отладочным портом, например:\n' +
        '  chrome --remote-debugging-port=9222 --user-data-dir=C:\\chrome-cdp http://localhost:5173',
    );
  }
  if (!res.ok) throw new Error(`ПРОВАЛ: ${url} ответил ${res.status} ${res.statusText}`);
  const data: unknown = await res.json();
  if (!Array.isArray(data)) throw new Error(`ПРОВАЛ: ${url} вернул не список вкладок`);
  return data.map((row, i) => {
    const t = row as Partial<CdpTarget>;
    if (typeof t.id !== 'string' || typeof t.url !== 'string' || typeof t.type !== 'string') {
      throw new Error(`ПРОВАЛ: в /json/list элемент ${i} без id/type/url: ${JSON.stringify(row).slice(0, 200)}`);
    }
    return { id: t.id, type: t.type, title: t.title ?? '', url: t.url, webSocketDebuggerUrl: t.webSocketDebuggerUrl };
  });
}

/**
 * Выбор вкладки с игрой. Ноль кандидатов или несколько без явной подсказки — ПРОВАЛ:
 * угадывать вкладку значит рисковать чужой игрой.
 */
export function pickGameTarget(targets: readonly CdpTarget[], urlHint = '5173'): CdpTarget {
  const pages = targets.filter((t) => t.type === 'page' && typeof t.webSocketDebuggerUrl === 'string');
  const game = pages.filter((t) => t.url.includes(urlHint));
  if (game.length === 1) return game[0];
  const listed = pages.map((t) => `  - ${t.url} (${t.title || 'без заголовка'})`).join('\n') || '  (пустых страниц нет)';
  if (game.length === 0) {
    throw new Error(
      `ПРОВАЛ: среди вкладок Chrome нет страницы с '${urlHint}'.\nОткрытые страницы:\n${listed}\n` +
        'Нужно: pnpm run dev в дереве игры → открыть http://localhost:5173 → выбрать «Play Offline» → войти в мир.',
    );
  }
  throw new Error(
    `ПРОВАЛ: под '${urlHint}' подходит ${game.length} вкладок — не угадываем.\n${listed}\n` +
      'Задай точную подсказку: --url-hint "localhost:5173".',
  );
}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
}

export interface EvaluateResult {
  value: unknown;
}

/** Сеанс CDP поверх сокета: запрос/ответ по id, события игнорируются осознанно. */
export class CdpSession {
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private closed: string | null = null;

  constructor(private readonly socket: SocketLike) {
    socket.onMessage((text) => this.onFrame(text));
    socket.onClose((code, reason) => this.failAll(`соединение с Chrome закрыто (код ${code}${reason ? `, ${reason}` : ''})`));
    socket.onError((message) => this.failAll(`ошибка сокета CDP: ${message}`));
  }

  private onFrame(text: string): void {
    const frame = parseCdpFrame(text);
    // События (method/params без id) нам не нужны: зонд работает запрос/ответ.
    if (frame.id === undefined) return;
    const pending = this.pending.get(frame.id);
    // Чужой id — не наша просьба (например, ответ другому клиенту отладки).
    if (!pending) return;
    this.pending.delete(frame.id);
    if (frame.error) {
      pending.reject(new Error(`ПРОВАЛ: CDP вернул ошибку ${frame.error.code ?? '?'}: ${frame.error.message ?? '?'}`));
    } else {
      pending.resolve(frame.result);
    }
  }

  private failAll(reason: string): void {
    this.closed = reason;
    for (const [, pending] of this.pending) pending.reject(new Error(`ПРОВАЛ: ${reason}`));
    this.pending.clear();
  }

  send(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
    assertAllowedMethod(method);
    if (this.closed) return Promise.reject(new Error(`ПРОВАЛ: сеанс CDP закрыт (${this.closed})`));
    const id = this.nextId++;
    return new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try {
        this.socket.send(JSON.stringify({ id, method, params }));
      } catch (e) {
        this.pending.delete(id);
        reject(e instanceof Error ? e : new Error(String(e)));
      }
    });
  }

  /** Вычислить выражение в странице и вернуть значение (returnByValue). */
  async evaluate(expression: string): Promise<unknown> {
    const raw = (await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })) as { result?: { value?: unknown }; exceptionDetails?: { text?: string; exception?: { description?: string } } };
    if (raw?.exceptionDetails) {
      const detail = raw.exceptionDetails.exception?.description ?? raw.exceptionDetails.text ?? 'без подробностей';
      throw new Error(`ПРОВАЛ: выражение в странице бросило исключение: ${detail}`);
    }
    return raw?.result?.value;
  }

  close(): void {
    this.failAll('сеанс закрыт агентом');
    // Сокет может быть уже закрыт — это не ошибка, а нормальный конец сеанса.
    try {
      this.socket.close();
    } catch {
      /* закрытие уже закрытого сокета не требует действий */
    }
  }
}

/** Открыть сеанс CDP к вкладке: сокет → ожидание open → CdpSession. */
export async function openCdpSession(
  wsUrl: string,
  opts: { factory?: SocketFactory; timeoutMs?: number } = {},
): Promise<CdpSession> {
  const { factory } = await resolveSocketFactory(opts.factory);
  const socket = await factory(wsUrl);
  const timeoutMs = opts.timeoutMs ?? 10_000;
  await new Promise<void>((resolve, reject) => {
    if (socket.readyState === 1) return resolve();
    const timer = setTimeout(
      () => reject(new Error(`ПРОВАЛ: сокет CDP не открылся к ${wsUrl} за ${timeoutMs} мс`)),
      timeoutMs,
    );
    socket.onOpen(() => {
      clearTimeout(timer);
      resolve();
    });
    socket.onError((message) => {
      clearTimeout(timer);
      reject(new Error(`ПРОВАЛ: сокет CDP к ${wsUrl} не открылся: ${message}`));
    });
  });
  return new CdpSession(socket);
}

/**
 * Выражение зонда: читает мир страницы каноном upstream. Только чтение —
 * никаких applyAction и записи в window.__game (проверяется тестом).
 * `moduleUrl` — URL модуля obs в dev-сервере vite (base '/' → '/src/sim/obs.ts').
 */
export function probeExpression(moduleUrl = '/src/sim/obs.ts'): string {
  return `(async () => {
  const g = window.__game;
  if (!g || !g.sim) return { inWorld: false, gameKeys: g ? Object.keys(g) : [] };
  const obs = await import(${JSON.stringify(moduleUrl)});
  const vector = obs.encodeObs(g.sim);
  return {
    inWorld: true,
    gameKeys: Object.keys(g),
    obsSize: obs.obsSize(),
    numActions: obs.NUM_ACTIONS,
    actionsLength: obs.ACTIONS.length,
    obsLength: vector.length,
    playerId: g.sim.playerId,
    firstObs: vector.slice(0, 16),
  };
})()`;
}

// ---------------------------------------------------------------------------
// Выбор ЖИВОЙ вкладки (урок замороженной линии: в браузере висят мёртвые вкладки
// с тем же URL, и бот «работал» ни с чем — `CdpClient.acquirePage()` в Java-линии
// решал ровно это). Проба только читает: никаких applyAction и записи.
// ---------------------------------------------------------------------------

/** Зонд живости вкладки. Возвращает факт, а не намерение. */
export function livenessExpression(): string {
  return `(() => {
  const g = window.__game;
  if (!g) return { live: false, reason: 'нет window.__game (страница не игра или мир не создан)' };
  if (!g.sim) return { live: false, reason: 'window.__game без sim (меню/загрузка)', gameKeys: Object.keys(g) };
  const p = g.sim.player;
  if (!p || !p.pos) return { live: false, reason: 'sim без player.pos (в мир не вошли)' };
  const w = g.world;
  return {
    live: true, reason: null,
    hp: p.hp, maxHp: p.maxHp, level: p.level, x: p.pos.x, z: p.pos.z,
    facing: p.facing, dead: !!p.dead, inCombat: !!p.inCombat,
    playerClass: String(p.class || p.playerClass || ''),
    entities: (g.sim.entities && typeof g.sim.entities.size === 'number') ? g.sim.entities.size : null,
    primaryId: (w && w.primaryId != null) ? w.primaryId : null,
    hasController: !!g.controller,
    controllerKeys: g.controller ? Object.keys(g.controller) : [],
    questStateApi: typeof g.sim.questState,
    href: location.href,
  };
})()`;
}

export interface LiveProbe {
  targetId: string;
  url: string;
  title: string;
  live: boolean;
  reason: string | null;
  detail?: Record<string, unknown>;
}

export type SessionFactory = (wsUrl: string) => Promise<CdpSession>;

/**
 * Пройти по вкладкам-кандидатам и найти ЖИВУЮ. Каждая проба открывает сеанс и
 * закрывает его, если вкладка не подошла (не оставлять за собой отладочных сессий).
 */
export async function probeLiveTargets(
  targets: readonly CdpTarget[],
  open: SessionFactory = openCdpSession,
): Promise<LiveProbe[]> {
  const out: LiveProbe[] = [];
  for (const t of targets) {
    if (!t.webSocketDebuggerUrl) {
      out.push({ targetId: t.id, url: t.url, title: t.title, live: false, reason: 'вкладка без webSocketDebuggerUrl' });
      continue;
    }
    let session: CdpSession;
    try {
      session = await open(t.webSocketDebuggerUrl);
    } catch (e) {
      out.push({ targetId: t.id, url: t.url, title: t.title, live: false, reason: (e as Error).message });
      continue;
    }
    try {
      const value = (await session.evaluate(livenessExpression())) as Record<string, unknown> | null;
      if (!value || typeof value !== 'object') {
        out.push({ targetId: t.id, url: t.url, title: t.title, live: false, reason: 'зонд не вернул объект' });
      } else if (value.live === true) {
        out.push({ targetId: t.id, url: t.url, title: t.title, live: true, reason: null, detail: value });
        continue; // сеанс живой вкладки НЕ закрываем — он нужен вызывающему
      } else {
        out.push({ targetId: t.id, url: t.url, title: t.title, live: false, reason: String(value.reason ?? 'не живая') });
      }
    } catch (e) {
      out.push({ targetId: t.id, url: t.url, title: t.title, live: false, reason: (e as Error).message });
    }
    session.close();
  }
  return out;
}

export interface AcquiredPage {
  session: CdpSession;
  target: CdpTarget;
  probe: LiveProbe;
  /** Все пробы — для честного отчёта о том, что ещё было открыто в браузере. */
  probes: LiveProbe[];
}

/**
 * Взять живую вкладку с игрой. Ноль живых или несколько без явного `--target-id` —
 * ПРОВАЛ: угадывание вкладки рискует чужой игрой.
 */
export async function acquireLivePage(
  opts: {
    cdpBase?: string;
    urlHint?: string;
    targetId?: string;
    fetchImpl?: typeof fetch;
    open?: SessionFactory;
  } = {},
): Promise<AcquiredPage> {
  const cdpBase = opts.cdpBase ?? 'http://127.0.0.1:9222';
  const urlHint = opts.urlHint ?? '5173';
  const open = opts.open ?? openCdpSession;
  const targets = await listTargets(cdpBase, opts.fetchImpl);
  const candidates = opts.targetId
    ? targets.filter((t) => t.id === opts.targetId)
    : targets.filter((t) => t.type === 'page' && t.url.includes(urlHint));
  if (opts.targetId && candidates.length === 0) {
    throw new Error(`ПРОВАЛ: вкладка с id '${opts.targetId}' не найдена в ${cdpBase}`);
  }
  if (candidates.length === 0) {
    const listed =
      targets.map((t) => `  - [${t.type}] ${t.url} (${t.title || 'без заголовка'})`).join('\n') || '  (вкладок нет)';
    throw new Error(
      `ПРОВАЛ: в Chrome на ${cdpBase} нет страницы с '${urlHint}'.\nОткрыто:\n${listed}\n` +
        'Нужно: в дереве игры `pnpm run dev` → http://localhost:5173 → «Play Offline» → войти в мир.',
    );
  }
  const probes = await probeLiveTargets(candidates, open);
  const live = probes.filter((p) => p.live);
  if (live.length === 0) {
    const listed = probes.map((p) => `  - ${p.url} (${p.title || 'без заголовка'}): ${p.reason}`).join('\n');
    throw new Error(
      `ПРОВАЛ: под '${urlHint}' найдено ${probes.length} вкладок, но ЖИВОЙ среди них нет.\n${listed}\n` +
        'Вкладка должна быть в мире: «Play Offline» → выбрать персонажа → войти.',
    );
  }
  if (live.length > 1 && !opts.targetId) {
    const listed = live.map((p) => `  - ${p.targetId} ${p.url}`).join('\n');
    throw new Error(`ПРОВАЛ: живых вкладок ${live.length} — не угадываем. Укажи --target-id:\n${listed}`);
  }
  const chosen = live[0];
  const target = candidates.find((t) => t.id === chosen.targetId);
  if (!target?.webSocketDebuggerUrl) throw new Error(`ПРОВАЛ: для живой вкладки ${chosen.targetId} нет webSocketDebuggerUrl`);
  // Сеанс уже открыт пробой, но probeLiveTargets не возвращает его наружу:
  // открываем свой, чтобы владелец был один и жизненный цикл был явным.
  const session = await open(target.webSocketDebuggerUrl);
  return { session, target, probe: chosen, probes };
}
