/**
 * Провод живого мира (задача A1): кадры рукопожатия, команд и ответов сервера.
 *
 * Правило линии: факты — из upstream, руками ничего не переписывается. Поэтому
 * все константы кадра импортируются из `game/src/world_api.ts` (он есть и в лёгком
 * дереве фактов), а возможности мира ВЫВОДЯТСЯ из таблицы команд `COMMAND_NAMES`,
 * а не объявляются на глаз: если upstream переименует токен, изменится и объявление.
 *
 * Факты v0.43.2 (файлы upstream в скобках):
 *  - первый кадр рукопожатия — `buildWebSocketAuthMessage` (src/net/world_auth_message.ts):
 *    `{t: ONLINE_WORLD_AUTH_TYPE, token, character, clientSeed, dungeonEntryFacingWire,
 *      timerWire, petSpecialWire, movementWire: 2}`; сервер сверяет каждое поле по
 *    точному равенству и при отсутствии молча понижает сессию на legacy-wire
 *    (server/ws_auth.ts) — поэтому поля заполняются только из констант игры;
 *  - `ONLINE_WORLD_AUTH_TYPE = 'auth-world-29'` (ONLINE_WORLD_LAYOUT_VERSION=29);
 *  - команды уходят кадром `{t:'cmd', cmd: <ClientCommand>, ...}` (src/net/online.ts:2222-2235);
 *    типизированный путь `cmd()` не выпускает dispatch-only токены — это гарантия tsc;
 *  - `DISPATCH_ONLY_COMMANDS` (src/world_api.ts:855) — dev-читы (`dev_level`,
 *    `dev_teleport`, `dev_give`, `dev_complete_quest`, ...) и RL-токен `targetNearest`:
 *    по проводу клиент их не отправляет. Агенту они запрещены и структурно;
 *  - движение — ОТДЕЛЬНЫЙ провод (`movementWire: 2`, `sendMovementFrame`,
 *    src/net/online.ts:2038-2094), не команда `cmd`;
 *  - отказ сервера всегда приходит кадром `{t:'error'}` ДО закрытия сокета
 *    (server/ws_auth.ts): клиент классифицирует литерал отказа, а отказ без кадра
 *    превращается в тихий цикл ретраев;
 *  - один персонаж = один сеанс: `planJoin` отвечает reject `'character already in world'`
 *    (server/linkdead.ts), повторный вход — только явным takeover
 *    (`POST /api/characters/:id/takeover`). Поэтому у агента СВОЙ персонаж.
 */
import {
  COMMAND_NAMES,
  DISPATCH_ONLY_COMMANDS,
  DUNGEON_ENTRY_FACING_WIRE_VERSION,
  ONLINE_WORLD_AUTH_TYPE,
  ONLINE_WORLD_LAYOUT_VERSION,
  PET_SPECIAL_WIRE_VERSION,
  STABLE_TIMER_WIRE_VERSION,
  type ClientCommand,
} from '../../game/src/world_api';
import type { QuestStateAccess, WorldCapabilities } from '../world/world';

/**
 * Версия movement-провода. В upstream это литерал `2` внутри
 * `buildWebSocketAuthMessage` (src/net/world_auth_message.ts) без экспортируемой
 * константы, поэтому здесь он объявлен отдельно и ПРИВЯЗАН тестом к upstream-помощнику,
 * когда дерево игры полное (tests/ws_live.test.ts). Без полного дерева тест честно
 * сообщает о пропуске, а не делает вид, что проверка была.
 */
export const MOVEMENT_WIRE_VERSION = 2 as const;

const COMMANDS: readonly string[] = COMMAND_NAMES as readonly string[];
const DISPATCH_ONLY: readonly string[] = DISPATCH_ONLY_COMMANDS as readonly string[];
const COMMAND_SET: ReadonlySet<string> = new Set(COMMANDS);
const DISPATCH_ONLY_SET: ReadonlySet<string> = new Set(DISPATCH_ONLY);

/** Есть ли токен в словаре команд мира (факт из таблицы upstream). */
export function hasCommand(token: string): boolean {
  return COMMAND_SET.has(token);
}

/** Токены, по которым объявлены груп-лут-ролы (need/greed, IWorldLoot.submitLootRoll). */
export function lootRollTokens(): string[] {
  return COMMANDS.filter((t) => t.includes('roll'));
}

/**
 * Проверка токена перед отправкой: неизвестный или dispatch-only — громкий ПРОВАЛ.
 * Dispatch-only — это dev-читы и RL-токены: их отправка была бы привилегированным
 * прогоном, который нельзя выдавать за обычный.
 */
export function assertClientCommand(token: string): asserts token is ClientCommand {
  if (DISPATCH_ONLY_SET.has(token)) {
    throw new Error(
      `ПРОВАЛ: команда '${token}' — dispatch-only (src/world_api.ts DISPATCH_ONLY_COMMANDS): ` +
        'это dev-чит или RL-токен стенда, по проводу живого мира клиент его не отправляет. ' +
        'Агент не пользуется привилегиями: такой прогон не считается переносимым.',
    );
  }
  if (!COMMAND_SET.has(token)) {
    throw new Error(
      `ПРОВАЛ: команды '${token}' нет в COMMAND_NAMES игры (v${ONLINE_WORLD_LAYOUT_VERSION} layout). ` +
        'Словарь команд берётся из upstream, придумывать токены нельзя.',
    );
  }
}

export interface AuthFrame {
  t: typeof ONLINE_WORLD_AUTH_TYPE;
  token: string;
  character: number;
  clientSeed: string;
  dungeonEntryFacingWire: typeof DUNGEON_ENTRY_FACING_WIRE_VERSION;
  timerWire: typeof STABLE_TIMER_WIRE_VERSION;
  petSpecialWire: typeof PET_SPECIAL_WIRE_VERSION;
  movementWire: typeof MOVEMENT_WIRE_VERSION;
}

/** Первый кадр рукопожатия — ровно тот, что требует server/ws_auth.ts. */
export function buildAuthFrame(input: { token: string; character: number; clientSeed?: string }): AuthFrame {
  const { token, character, clientSeed = '' } = input;
  if (typeof token !== 'string' || token.length === 0) {
    throw new Error('ПРОВАЛ: пустой token — сначала REST-вход (/api/login), токен берётся оттуда и в журнал не печатается.');
  }
  if (!Number.isInteger(character) || character <= 0) {
    throw new Error(`ПРОВАЛ: character должен быть целым id персонажа (>0), получено ${String(character)}.`);
  }
  return {
    t: ONLINE_WORLD_AUTH_TYPE,
    token,
    character,
    clientSeed,
    dungeonEntryFacingWire: DUNGEON_ENTRY_FACING_WIRE_VERSION,
    timerWire: STABLE_TIMER_WIRE_VERSION,
    petSpecialWire: PET_SPECIAL_WIRE_VERSION,
    movementWire: MOVEMENT_WIRE_VERSION,
  };
}

/** Кадр команды: `{t:'cmd', cmd, ...args}` — форма rawCmd из src/net/online.ts. */
export function buildCommandFrame(
  cmd: ClientCommand,
  args: Record<string, unknown> = {},
): { t: 'cmd'; cmd: ClientCommand } & Record<string, unknown> {
  assertClientCommand(cmd);
  if ('t' in args || 'cmd' in args) {
    throw new Error("ПРОВАЛ: аргументы команды не должны переопределять поля 't' и 'cmd'.");
  }
  // Грабли, описанные самим upstream (scripts/lib/world_auth.mjs): чат и каждый
  // «/dev ...»-чит едут КОМАНДОЙ ({t:'cmd', cmd:'chat', text}), а кадр {t:'chat'}
  // верхнего уровня сервер молча выбрасывает — скрипт при этом верит, что боты
  // прокачаны и одеты. Поэтому чит в тексте чата мы ловим здесь, а не надеемся
  // на сервер: привилегированный прогон не должен выдаваться за обычный.
  if (cmd === ('chat' as ClientCommand)) {
    const text = typeof args.text === 'string' ? args.text : '';
    if (/^\s*\/\s*dev(\b|_)/i.test(text)) {
      throw new Error(
        `ПРОВАЛ: текст чата '${text.slice(0, 60)}' — dev-чит. Агент привилегиями не пользуется: ` +
          'такой прогон не переносим и в evidence объявляется отдельно (ALLOW_DEV_COMMANDS).',
      );
    }
  }
  return { t: 'cmd', cmd, ...args };
}

export function encodeFrame(frame: unknown): string {
  return JSON.stringify(frame);
}

export interface ServerFrame {
  t: string;
  [key: string]: unknown;
}

/**
 * Разбор кадра сервера. Не-JSON или кадр без `t` — громкий ПРОВАЛ: молча пропустить
 * кадр значит потерять отказ сервера (а отказ без кадра клиент превращает в вечный ретрай).
 */
export function parseFrame(text: string): ServerFrame {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (e) {
    throw new Error(`ПРОВАЛ: кадр сервера не JSON (${(e as Error).message}): ${text.slice(0, 200)}`);
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`ПРОВАЛ: кадр сервера не объект: ${text.slice(0, 200)}`);
  }
  const t = (value as { t?: unknown }).t;
  if (typeof t !== 'string' || t.length === 0) {
    throw new Error(`ПРОВАЛ: в кадре сервера нет строкового 't': ${text.slice(0, 200)}`);
  }
  return value as ServerFrame;
}

export const ERROR_FRAME_NOTE =
  'Отказ сервера приходит кадром {t:"error"} ДО закрытия сокета (server/ws_auth.ts): ' +
  'литералы отказа — wire-контракт, клиент их классифицирует. Отказ без кадра = тихий цикл ретраев.';

/** То, что обязан ИЗМЕРИТЬ живой сеанс, прежде чем мы это объявим. */
export interface MeasuredLiveFacts {
  /** Задержка связи, мс. Обязательна: выдуманная задержка — подделка доказательства. */
  latencyMs: number;
  /** Идентичность сущностей в снапшоте: есть ли id, живущий между кадрами. */
  entityIdentity?: 'stable' | 'slot';
  absoluteCoords?: boolean;
  entityTemplates?: boolean;
  entityAbsoluteHp?: boolean;
  damageCounters?: boolean;
  questObjectiveCounts?: boolean;
  itemCountApi?: boolean;
  questStateApi?: QuestStateAccess;
}

/**
 * Возможности живого мира. Всё неизмеренное объявляется КОНСЕРВАТИВНО
 * (меньше, чем «есть»), потому что заявленная возможность разрешает политике
 * на неё опираться. Производные от словаря команд (цель, сдача/отказ квеста,
 * продавец, груп-лут) берутся из таблицы upstream, а не задаются руками.
 */
export function liveWorldCapabilities(m: MeasuredLiveFacts): WorldCapabilities {
  if (!Number.isFinite(m.latencyMs) || m.latencyMs < 0) {
    throw new Error(`ПРОВАЛ: latencyMs обязана быть измерена (>=0 мс), получено ${String(m.latencyMs)}.`);
  }
  return {
    transport: 'websocket',
    absoluteCoords: m.absoluteCoords ?? false,
    questStateApi: m.questStateApi ?? 'none',
    itemCountApi: m.itemCountApi ?? false,
    // Контент (квесты, мобы, лагеря) мы берём из дерева игры, а не из мира, —
    // поэтому true независимо от транспорта (как и у стенда).
    contentData: true,
    // Живой сервер не воспроизводим: снапшоты 50 мс, другие игроки, рейт-окна.
    deterministic: false,
    frameSkip: 0,
    realtime: true,
    otherPlayers: true,
    targetSelection: hasCommand('target') && hasCommand('tab') ? 'free' : 'nearest-only',
    abandonQuest: hasCommand('abandon'),
    vendor: hasCommand('buy') && hasCommand('sell'),
    partyLootRolls: lootRollTokens().length > 0,
    commandVocabulary: 'wire-commands',
    entityIdentity: m.entityIdentity ?? 'slot',
    entityTemplates: m.entityTemplates ?? false,
    entityAbsoluteHp: m.entityAbsoluteHp ?? false,
    damageCounters: m.damageCounters ?? false,
    questObjectiveCounts: m.questObjectiveCounts ?? false,
    latencyMs: m.latencyMs,
  };
}

/** Что именно не измерено — печатается рядом с объявлением возможностей. */
export function unmeasuredCapabilityNotes(m: MeasuredLiveFacts): string[] {
  const checks: Array<[keyof MeasuredLiveFacts, string]> = [
    ['entityIdentity', "идентичность сущностей объявлена 'slot' (позиция в списке НЕ личность)"],
    ['absoluteCoords', 'абсолютные координаты объявлены недоступными'],
    ['entityTemplates', 'вид сущности (templateId) объявлен недоступным'],
    ['entityAbsoluteHp', 'абсолютное HP объявлено недоступным'],
    ['damageCounters', 'счётчики урона объявлены нулевыми (не сигнал)'],
    ['questObjectiveCounts', 'счётчики по целям квеста объявлены недоступными'],
    ['itemCountApi', 'чтение количества предметов объявлено недоступным'],
    ['questStateApi', "состояние квестов объявлено 'none' (запрос бросит исключение)"],
  ];
  return checks.filter(([key]) => m[key] === undefined).map(([, note]) => `не измерено → ${note}`);
}
