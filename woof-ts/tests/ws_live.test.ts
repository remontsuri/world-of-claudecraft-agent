// Живой мир (задача A1): провод и сокет. Проверяется то, что проверяется БЕЗ
// сервера: кадры собираются из констант upstream, привилегированные команды
// (dev-читы, RL-токены) отправить нельзя, неизмеренные возможности объявляются
// консервативно, а сокет разрешается в объявленном порядке и громко проваливается,
// если открывать нечем. Живая приёмка (A1.5: убийство и квест за сервером :8787) —
// отдельный шаг, она требует docker compose и здесь не подменяется моками.
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import {
  COMMAND_NAMES,
  DISPATCH_ONLY_COMMANDS,
  DUNGEON_ENTRY_FACING_WIRE_VERSION,
  ONLINE_WORLD_AUTH_TYPE,
  PET_SPECIAL_WIRE_VERSION,
  STABLE_TIMER_WIRE_VERSION,
} from '../game/src/world_api';
import {
  ERROR_FRAME_NOTE,
  MOVEMENT_WIRE_VERSION,
  assertClientCommand,
  buildAuthFrame,
  buildCommandFrame,
  encodeFrame,
  hasCommand,
  liveWorldCapabilities,
  lootRollTokens,
  parseFrame,
  unmeasuredCapabilityNotes,
} from '../src/bridge/ws_protocol';
import {
  NO_SOCKET_MESSAGE,
  SOCKET_OPEN,
  adaptSocket,
  resolveSocketFactory,
  type SocketLike,
} from '../src/bridge/ws_socket';

/** browser-style сокет (глобальный WebSocket): поля-обработчики, а не emit. */
function fakeBrowserSocket() {
  const sent: string[] = [];
  let closed = 0;
  const sock = {
    readyState: SOCKET_OPEN,
    send: (data: string) => void sent.push(data),
    close: () => void (closed += 1),
    onopen: null as ((ev: unknown) => void) | null,
    onmessage: null as ((ev: { data: unknown }) => void) | null,
    onclose: null as ((ev: { code?: number; reason?: string }) => void) | null,
    onerror: null as ((ev: unknown) => void) | null,
  };
  return { sock, sent, isClosed: () => closed > 0 };
}

/** сокет пакета `ws`: EventEmitter (on/emit), как в bot/gateway.ts игры. */
function fakeNodeWsSocket() {
  const sent: string[] = [];
  const handlers = new Map<string, Array<(...args: unknown[]) => void>>();
  const sock = {
    readyState: SOCKET_OPEN,
    send: (data: string) => void sent.push(data),
    close: () => undefined,
    on: (event: string, cb: (...args: unknown[]) => void) => {
      const list = handlers.get(event) ?? [];
      list.push(cb);
      handlers.set(event, list);
      return sock;
    },
  };
  const emit = (event: string, ...args: unknown[]): void => {
    for (const cb of handlers.get(event) ?? []) cb(...args);
  };
  return { sock, sent, emit };
}

describe('кадр рукопожатия', () => {
  it('собирается из констант игры, а не из наших догадок', () => {
    const frame = buildAuthFrame({ token: 'tok', character: 7 });
    expect(frame.t).toBe(ONLINE_WORLD_AUTH_TYPE);
    expect(frame.timerWire).toBe(STABLE_TIMER_WIRE_VERSION);
    expect(frame.petSpecialWire).toBe(PET_SPECIAL_WIRE_VERSION);
    expect(frame.dungeonEntryFacingWire).toBe(DUNGEON_ENTRY_FACING_WIRE_VERSION);
    expect(frame.movementWire).toBe(MOVEMENT_WIRE_VERSION);
    expect(frame.character).toBe(7);
    expect(frame.clientSeed).toBe('');
    // server/ws_auth.ts сверяет каждое объявленное поле по точному равенству и
    // при отсутствии молча понижает сессию на legacy-wire: набор ключей фиксирован.
    expect(Object.keys(frame).sort()).toEqual(
      ['t', 'token', 'character', 'clientSeed', 'dungeonEntryFacingWire', 'timerWire', 'petSpecialWire', 'movementWire'].sort(),
    );
  });

  const upstreamHelper = 'game/src/net/world_auth_message.ts';
  const hasFullTree = existsSync(upstreamHelper);
  if (!hasFullTree) {
    // Честный пропуск, а не видимость проверки: лёгкое дерево фактов не содержит
    // src/net. Полное дерево даёт GAME_FULL=1 bash tools/setup_game.sh.
    console.warn(
      `[ws_live] пропуск привязки к upstream-помощнику: нет ${upstreamHelper} (нужен GAME_FULL=1 клон). ` +
        `Значение movementWire=${MOVEMENT_WIRE_VERSION} в этом прогоне НЕ сверено с buildWebSocketAuthMessage.`,
    );
  }
  // Литерал `movementWire: 2` в upstream не экспортируется константой, поэтому
  // единственная честная привязка — чтение исходника помощника. Нет полного дерева
  // (src/net) — тест пропускается ВСЛУХ, а не делает вид, что сверка была.
  it.skipIf(!hasFullTree)('движение: movementWire совпадает с литералом upstream-помощника', () => {
    const src = readFileSync(upstreamHelper, 'utf8');
    const m = /movementWire:\s*(\d+)/.exec(src);
    expect(m, `в ${upstreamHelper} не найден movementWire — помощник изменился, сверь кадр руками`).not.toBeNull();
    expect(Number(m?.[1])).toBe(MOVEMENT_WIRE_VERSION);
    // и весь набор объявленных возможностей помощника остаётся тем же
    for (const key of ['dungeonEntryFacingWire', 'timerWire', 'petSpecialWire', 'clientSeed']) {
      expect(src).toContain(key);
      expect(Object.keys(buildAuthFrame({ token: 'tok', character: 7 }))).toContain(key);
    }
  });

  it('пустой токен и кривой id персонажа — ПРОВАЛ, а не кадр', () => {
    expect(() => buildAuthFrame({ token: '', character: 1 })).toThrow(/пустой token/);
    expect(() => buildAuthFrame({ token: 'tok', character: 0 })).toThrow(/целым id персонажа/);
    expect(() => buildAuthFrame({ token: 'tok', character: 1.5 })).toThrow(/целым id персонажа/);
  });
});

describe('кадр команды', () => {
  it('форма {t:"cmd", cmd, ...args} — как rawCmd в src/net/online.ts', () => {
    expect(buildCommandFrame('attack')).toEqual({ t: 'cmd', cmd: 'attack' });
    expect(buildCommandFrame('cast', { slot: 3 })).toEqual({ t: 'cmd', cmd: 'cast', slot: 3 });
    expect(JSON.parse(encodeFrame(buildCommandFrame('loot')))).toEqual({ t: 'cmd', cmd: 'loot' });
  });

  it('dev-читы и RL-токены отправить нельзя (привилегированный прогон запрещён)', () => {
    for (const token of ['dev_level', 'dev_teleport', 'dev_give', 'dev_complete_quest', 'targetNearest']) {
      expect(DISPATCH_ONLY_COMMANDS).toContain(token);
      expect(() => assertClientCommand(token)).toThrow(/dispatch-only/);
      expect(() => buildCommandFrame(token as never)).toThrow(/dispatch-only/);
    }
  });

  it('придуманного токена в словаре нет — ПРОВАЛ, а не молчаливая отправка', () => {
    expect(hasCommand('fly_to_moon')).toBe(false);
    expect(() => buildCommandFrame('fly_to_moon' as never)).toThrow(/COMMAND_NAMES/);
  });

  it('dev-чит в тексте чата — ПРОВАЛ (грабли upstream: чат и /dev едут одной командой)', () => {
    expect(buildCommandFrame('chat' as never, { text: 'привет' })).toEqual({ t: 'cmd', cmd: 'chat', text: 'привет' });
    expect(() => buildCommandFrame('chat' as never, { text: '/dev level 60' })).toThrow(/dev-чит/);
    expect(() => buildCommandFrame('chat' as never, { text: '  /dev_teleport' })).toThrow(/dev-чит/);
  });

  it('аргументы не переопределяют служебные поля кадра', () => {
    expect(() => buildCommandFrame('cast', { t: 'cmd2' })).toThrow(/переопределять/);
    expect(() => buildCommandFrame('cast', { cmd: 'loot' })).toThrow(/переопределять/);
  });
});

describe('разбор кадра сервера', () => {
  it('JSON-объект с t разбирается, остальное — ПРОВАЛ', () => {
    expect(parseFrame('{"t":"error","error":"character already in world"}').t).toBe('error');
    expect(() => parseFrame('не json')).toThrow(/не JSON/);
    expect(() => parseFrame('[1,2]')).toThrow(/не объект/);
    expect(() => parseFrame('{"cmd":"attack"}')).toThrow(/нет строкового 't'/);
  });

  it('отказ сервера — это кадр {t:"error"} до закрытия сокета', () => {
    expect(ERROR_FRAME_NOTE).toMatch(/\{t:"error"\}/);
    expect(ERROR_FRAME_NOTE).toMatch(/character already in world|литералы отказа/);
  });
});

describe('возможности живого мира', () => {
  it('выводятся из словаря команд upstream, а не задаются руками', () => {
    const caps = liveWorldCapabilities({ latencyMs: 12 });
    expect(hasCommand('target') && hasCommand('tab')).toBe(true);
    expect(caps.targetSelection).toBe('free');
    expect(hasCommand('abandon')).toBe(true);
    expect(caps.abandonQuest).toBe(true);
    expect(hasCommand('buy') && hasCommand('sell')).toBe(true);
    expect(caps.vendor).toBe(true);
    // Груп-лут: IWorldLoot.submitLootRoll в upstream есть, а токен команды ищем в
    // таблице; объявление обязано совпадать с фактом, а не с нашим ожиданием.
    expect(caps.partyLootRolls).toBe(lootRollTokens().length > 0);
    expect(caps.commandVocabulary).toBe('wire-commands');
    expect(COMMAND_NAMES.length).toBeGreaterThan(100);
  });

  it('живой мир объявляется недетерминированным, реальным и многопользовательским', () => {
    const caps = liveWorldCapabilities({ latencyMs: 12 });
    expect(caps.transport).toBe('websocket');
    expect(caps.deterministic).toBe(false);
    expect(caps.realtime).toBe(true);
    expect(caps.otherPlayers).toBe(true);
    expect(caps.frameSkip).toBe(0);
    expect(caps.contentData).toBe(true);
  });

  it('всё неизмеренное объявлено консервативно (меньше, чем «есть»)', () => {
    const caps = liveWorldCapabilities({ latencyMs: 12 });
    expect(caps.entityIdentity).toBe('slot');
    expect(caps.questStateApi).toBe('none');
    expect(caps.entityTemplates).toBe(false);
    expect(caps.entityAbsoluteHp).toBe(false);
    expect(caps.damageCounters).toBe(false);
    expect(caps.questObjectiveCounts).toBe(false);
    expect(caps.absoluteCoords).toBe(false);
    expect(caps.itemCountApi).toBe(false);
    expect(unmeasuredCapabilityNotes({ latencyMs: 12 })).toHaveLength(8);
  });

  it('измеренное переопределяет консервативный дефолт, заметки сокращаются', () => {
    const caps = liveWorldCapabilities({
      latencyMs: 4,
      entityIdentity: 'stable',
      questStateApi: 'observed',
      entityTemplates: true,
    });
    expect(caps.entityIdentity).toBe('stable');
    expect(caps.questStateApi).toBe('observed');
    expect(caps.entityTemplates).toBe(true);
    expect(unmeasuredCapabilityNotes({ latencyMs: 4, entityIdentity: 'stable', questStateApi: 'observed', entityTemplates: true })).toHaveLength(5);
  });

  it('задержку нельзя выдумать — только измерить', () => {
    expect(() => liveWorldCapabilities({ latencyMs: Number.NaN })).toThrow(/latencyMs/);
    expect(() => liveWorldCapabilities({ latencyMs: -1 })).toThrow(/latencyMs/);
  });
});

describe('сокет живого мира', () => {
  it('инжектированная фабрика побеждает (тесты и явный выбор владельца)', async () => {
    const fake = (): SocketLike => adaptSocket(fakeBrowserSocket().sock);
    const resolved = await resolveSocketFactory(fake);
    expect(resolved.arm).toBe('injected');
    expect(resolved.describe()).toMatch(/инжектированная/);
  });

  it('адаптер browser-style сокета: текст туда, кадры оттуда, бинарь декодируется', () => {
    const { sock, sent, isClosed } = fakeBrowserSocket();
    const adapted = adaptSocket(sock);
    const got: string[] = [];
    adapted.onMessage((text) => got.push(text));
    adapted.send('{"t":"cmd","cmd":"attack"}');
    sock.onmessage?.({ data: '{"t":"snapshot"}' });
    sock.onmessage?.({ data: new TextEncoder().encode('{"t":"hello"}') });
    adapted.close();
    expect(sent).toEqual(['{"t":"cmd","cmd":"attack"}']);
    expect(got).toEqual(['{"t":"snapshot"}', '{"t":"hello"}']);
    expect(isClosed()).toBe(true);
    expect(adapted.readyState).toBe(SOCKET_OPEN);
  });

  it('не-текстовый и не-байтовый кадр — ПРОВАЛ, а не догадка', () => {
    const { sock } = fakeBrowserSocket();
    const adapted = adaptSocket(sock);
    adapted.onMessage(() => undefined);
    expect(() => sock.onmessage?.({ data: { blob: true } })).toThrow(/не текст и не байты/);
  });

  it('адаптер сокета `ws`: события open/message/close/error', () => {
    const { sock, sent, emit } = fakeNodeWsSocket();
    const adapted = adaptSocket(sock);
    const seen: string[] = [];
    let opened = 0;
    let closed = '';
    let failed = '';
    adapted.onOpen(() => (opened += 1));
    adapted.onMessage((text) => seen.push(text));
    adapted.onClose((code, reason) => (closed = `${code}:${reason}`));
    adapted.onError((message) => (failed = message));
    emit('open');
    adapted.send('{"t":"cmd","cmd":"loot"}');
    emit('message', Buffer.from('{"t":"snapshot"}', 'utf8'));
    emit('error', new Error('соединение сброшено'));
    emit('close', 1006, Buffer.from('', 'utf8'));
    expect(opened).toBe(1);
    expect(sent).toEqual(['{"t":"cmd","cmd":"loot"}']);
    expect(seen).toEqual(['{"t":"snapshot"}']);
    expect(failed).toBe('соединение сброшено');
    expect(closed).toBe('1006:');
  });

  it('порядок разрешения: глобальный WebSocket (Node 22+) раньше пакета ws', async () => {
    const g = globalThis as { WebSocket?: unknown };
    const saved = g.WebSocket;
    try {
      const { sock } = fakeBrowserSocket();
      g.WebSocket = class {
        constructor(_url: string) {
          return sock as unknown as object;
        }
      };
      const resolved = await resolveSocketFactory();
      expect(resolved.arm).toBe('global');
      expect(resolved.describe()).toMatch(/глобальный WebSocket/);
    } finally {
      if (saved === undefined) delete g.WebSocket;
      else g.WebSocket = saved;
    }
  });

  it('на Node 20 без глобального сокета берётся пакет ws (зависимость объявлена)', async () => {
    const g = globalThis as { WebSocket?: unknown };
    const saved = g.WebSocket;
    delete g.WebSocket;
    try {
      const resolved = await resolveSocketFactory();
      expect(resolved.arm).toBe('ws');
      expect(resolved.describe()).toMatch(/пакет ws/);
    } finally {
      if (saved !== undefined) g.WebSocket = saved;
    }
  });

  it('сообщение об отсутствии сокета называет оба лекарства', () => {
    expect(NO_SOCKET_MESSAGE).toMatch(/Node 22/);
    expect(NO_SOCKET_MESSAGE).toMatch(/npm install ws/);
    expect(NO_SOCKET_MESSAGE).toMatch(/ПРОВАЛ/);
  });
});
