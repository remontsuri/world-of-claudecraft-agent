/**
 * WebSocket-сокет для живого мира (задача A1, схема «агент — отдельный клиент
 * авторитетного сервера :8787»).
 *
 * Почему так, а не иначе (факты из upstream v0.43.2):
 *  - сервер поднимает WS на `/ws` (server/main.ts, upgrade-обвязка `createWsAuth`);
 *  - свой Node-бот игра пишет точно так же: `bot/gateway.ts` — инъекция
 *    `socketFactory: (url) => new WebSocket(url)`, продакшен-реализация — клиент
 *    `ws`, в тестах заглушка; `tsconfig.bot.json`: `types: ["node"]`, lib ES2022,
 *    без DOM. Мы повторяем этот рисунок: фабрика инжектируется, типы — свои,
 *    DOM-lib не нужен;
 *  - сама игра зависит от `ws@^8.21.0` (package.json игры).
 *
 * Порядок разрешения (тихий фолбэк запрещён — вместо него громкий ПРОВАЛ):
 *   1. инжектированная фабрика (тесты, особый владелец);
 *   2. `globalThis.WebSocket` — Node 22+, ноль зависимостей;
 *   3. `import('ws')` — Node 20, одна зависимость (та же библиотека, что у игры);
 *   4. ПРОВАЛ с двумя лекарствами. Никакого «попробуем без сокета».
 */

/** То, что нужно транспорту от сокета. Намеренно узко: ни DOM, ни `ws`-типов. */
export interface SocketLike {
  /** 1 = OPEN (совпадает и у browser-style, и у `ws`). */
  readonly readyState: number;
  send(text: string): void;
  close(code?: number, reason?: string): void;
  onOpen(cb: () => void): void;
  onMessage(cb: (text: string) => void): void;
  onClose(cb: (code: number, reason: string) => void): void;
  onError(cb: (message: string) => void): void;
}

export type SocketFactory = (url: string) => SocketLike | Promise<SocketLike>;
export type SocketArm = 'injected' | 'global' | 'ws';

export interface ResolvedSocket {
  readonly factory: SocketFactory;
  readonly arm: SocketArm;
  /** Человекочитаемая строка для журнала: чем именно открыт сокет. */
  describe(): string;
}

export const SOCKET_OPEN = 1;

/** browser-style сокет (глобальный WebSocket в Node 22+ / браузере). */
interface BrowserStyleSocket {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code?: number; reason?: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

/** сокет пакета `ws` (EventEmitter). */
interface NodeWsSocket {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  on(event: 'open', cb: () => void): unknown;
  on(event: 'message', cb: (data: unknown) => void): unknown;
  on(event: 'close', cb: (code: number, reason: unknown) => void): unknown;
  on(event: 'error', cb: (err: unknown) => void): unknown;
}

export const NO_SOCKET_MESSAGE = [
  'ПРОВАЛ: в этом Node нечем открыть WebSocket к живому миру.',
  'Лекарство 1 (ноль зависимостей): Node 22+ — там глобальный WebSocket встроен.',
  "Лекарство 2 (Node 20): npm install ws@^8 — ту же библиотеку использует сама игра.",
  'Проверить: node -v; node -e "console.log(typeof globalThis.WebSocket)"',
].join('\n');

/** Текст кадра: сервер шлёт JSON-текст. Blob/бинарь — громкий ПРОВАЛ, не догадка. */
function frameText(data: unknown): string {
  if (typeof data === 'string') return data;
  if (data instanceof Uint8Array) return new TextDecoder().decode(data);
  throw new Error(
    `ПРОВАЛ: кадр сокета не текст и не байты (${typeof data}). Ждём JSON-текст от сервера игры; ` +
      'другие форматы не поддерживаем и не угадываем.',
  );
}

/**
 * Адаптер к SocketLike. Публичный и тестируемый шов: обе реализации сокета
 * (browser-style и `ws`) обязаны давать транспорту один и тот же узкий интерфейс.
 */
export function isNodeWs(s: unknown): s is NodeWsSocket {
  return typeof (s as { on?: unknown })?.on === 'function';
}

export function adaptSocket(s: unknown): SocketLike {
  if (isNodeWs(s)) {
    const ws = s;
    return {
      get readyState() {
        return ws.readyState;
      },
      send: (text) => ws.send(text),
      close: (code, reason) => (code === undefined ? ws.close() : ws.close(code, reason)),
      onOpen: (cb) => void ws.on('open', cb),
      onMessage: (cb) => void ws.on('message', (d) => cb(frameText(d))),
      onClose: (cb) => void ws.on('close', (code, reason) => cb(code, frameText(reason ?? ''))),
      onError: (cb) => void ws.on('error', (e) => cb(String((e as Error)?.message ?? e))),
    };
  }
  const ws = s as BrowserStyleSocket;
  return {
    get readyState() {
      return ws.readyState;
    },
    send: (text) => ws.send(text),
    close: (code, reason) => (code === undefined ? ws.close() : ws.close(code, reason)),
    onOpen: (cb) => {
      ws.onopen = () => cb();
    },
    onMessage: (cb) => {
      ws.onmessage = (ev) => cb(frameText(ev?.data));
    },
    onClose: (cb) => {
      ws.onclose = (ev) => cb(ev?.code ?? 0, ev?.reason ?? '');
    },
    onError: (cb) => {
      ws.onerror = () => cb('ошибка сокета (browser-style, без подробностей)');
    },
  };
}

/**
 * Чем открывать сокет. `explicit` побеждает всё (тесты и владелец).
 * Бросает NO_SOCKET_MESSAGE, если ни одной реализации нет.
 */
export async function resolveSocketFactory(explicit?: SocketFactory): Promise<ResolvedSocket> {
  if (explicit) {
    return {
      factory: explicit,
      arm: 'injected',
      describe: () => 'сокет: инжектированная фабрика (тест или явный выбор владельца)',
    };
  }
  const g = (globalThis as { WebSocket?: new (url: string) => unknown }).WebSocket;
  if (typeof g === 'function') {
    return {
      factory: (url) => adaptSocket(new g(url)),
      arm: 'global',
      describe: () => 'сокет: глобальный WebSocket этого Node (ноль зависимостей)',
    };
  }
  try {
    const mod = (await import('ws')) as {
      default?: new (url: string) => unknown;
      WebSocket?: new (url: string) => unknown;
    };
    const Ctor = mod.default ?? mod.WebSocket;
    if (typeof Ctor === 'function') {
      return {
        factory: (url) => adaptSocket(new Ctor(url)),
        arm: 'ws',
        describe: () => 'сокет: пакет ws (та же библиотека, которую использует игра)',
      };
    }
  } catch {
    // Не резолвится — это не тихий фолбэк: ниже громкий ПРОВАЛ с лекарствами.
  }
  throw new Error(NO_SOCKET_MESSAGE);
}
