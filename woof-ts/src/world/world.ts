/**
 * world.ts — шов между агентом и миром.
 *
 * Зачем: целевой мир сопоставим с миром онлайн-игры, а не с тепличным
 * детерминированным стендом. Значит in-process `Sim` — это ОДИН из адаптеров,
 * а не основа архитектуры. Всё, что умеет агент (FSM, арбитраж, память,
 * исполнитель), обязано работать через этот интерфейс и через объявленные
 * возможности мира, а не через привилегии конкретного стенда.
 *
 * Правило проекта: никаких молчаливых запасных вариантов. Если мир чего-то не
 * даёт (абсолютных координат, состояния чужого квеста, числа предметов), это
 * объявлено в `capabilities`, напечатано до прогона, записано в evidence, а
 * зависящий от этого код либо не вызывается, либо честно сообщает
 * «не проверено» — но не делает вид, что всё в порядке.
 *
 * Адаптеры:
 *   - sim_world.ts  — in-process `Sim` из дерева игры (стенд, детерминирован);
 *   - (план) net_world.ts — NDJSON-клиент к headless env server
 *     (`headless/env_server.ts`: info/reset/step, obs=number[], action=int);
 *   - (план) live_world.ts — клиент авторитетного сервера (`npm run server`,
 *     :8787, `/ws`): реальное время, другие игроки, права на лут, задержки.
 */
import type { AbilityView, StepResult } from './sim_world';
import type { GameFacts } from '../facts';
import type { Counters, WorldModel } from './types';

/** Что мир честно предоставляет агенту. Всё, чего здесь нет, — не используется. */
/** Уровень доступа к состоянию квестов (см. questStateApi). */
export type QuestStateAccess = 'full' | 'observed' | 'none';

export interface WorldCapabilities {
    /** Транспорт: как агент связан с миром. 'cdp' — мир живёт в странице браузера
     *  (офлайн-режим Vite), связь через Chrome DevTools Protocol. */
    transport: 'in-process' | 'ndjson-stdio' | 'websocket' | 'cdp' | 'unknown';
  /** Мир отдаёт абсолютные координаты сущностей.
   *  В RL-наблюдении игры их нет — там только дистанция/пеленг, поэтому
   *  навигация по координатам лагерей при transport!='in-process' должна
   *  опираться на собственное счисление пути, а не на координаты мира. */
  absoluteCoords: boolean;
  /** Доступ к состоянию квестов. Три уровня, и они НЕ взаимозаменяемы:
   *  - 'full'     — можно спросить состояние ЛЮБОГО квеста (Sim.questState):
   *                 различимы available/active/ready/done/none;
   *  - 'observed' — только то, что мир сам показывает в наблюдении: по RL-obs
   *                 игры точно различимы active(0.33)/ready(0.66)/done(1), а
   *                 ноль НЕРАЗЛИЧИМ между available и none/failed, поэтому
   *                 «квест доступен» по проводу не утверждается никогда;
   *  - 'none'     — ничего.
   *  Подмена 'observed' на 'full' означала бы угадывание доступности квестов —
   *  ровно тот класс молчаливых допущений, который проект запрещает. */
  questStateApi: QuestStateAccess;
  /** Можно прочитать количество предмета в сумках (Sim.countItem / инвентарь клиента). */
  itemCountApi: boolean;
  /** Доступны определения контента игры (квесты, мобы, лагеря) — у клиента они тоже есть. */
  contentData: boolean;
  /** Детерминированный replay при фиксированном seed. */
  deterministic: boolean;
  /** Тиков мира на одно решение агента (frameSkip стенда; в живом мире — 0). */
  frameSkip: number;
  /** Мир идёт в реальном времени: решение обязано укладываться в его темп. */
  realtime: boolean;
  /** В мире есть другие игроки (конкуренция за мобов, права на лут, FFA, PvP). */
  otherPlayers: boolean;
  /** Возможности боя/квестов/торговли — то, чем онлайн-мир богаче headless-стенда
   *  (факты из src/world_api.ts игры: фасеты IWorldTargeting/IWorldQuests/
   *  IWorldInventory/IWorldLoot; `targetNearest` там помечен как RL-only
   *  dispatch-only токен, по проводу не ходит). */
  targetSelection: 'nearest-only' | 'free';
  abandonQuest: boolean;
  vendor: boolean;
  partyLootRolls: boolean;
    /** Словарь команд мира: RL-действия стенда, wire-команды сервера или
     *  'page-api' — публичные методы `window.__game.sim`/`controller` в браузере. */
    commandVocabulary: 'rl-actions' | 'wire-commands' | 'page-api';
  /** Идентичность сущностей в наблюдении:
   *  - 'stable' — у каждой сущности есть id, живущий между кадрами (in-process Sim);
   *  - 'slot'   — мир показывает только «ближайших» без id: позиция в списке
   *               НЕ является личностью, между кадрами слоты переставляются.
   *    Всё, что помнит сущность по id (журнал убийств, «эт труп уже обобран»),
   *    в этом режиме недостоверно и обязано быть заявлено как неподдерживаемое. */
  entityIdentity: 'stable' | 'slot';
  /** Известен ли вид сущности (templateId): у стенда — да, по RL-obs — нет,
   *  там есть только уровень относительно игрока и доля HP. Без вида нельзя
   *  проверить «тот ли это моб, которого требует квест». */
  entityTemplates: boolean;
  /** Известно ли абсолютное HP сущности (а не только доля). */
  entityAbsoluteHp: boolean;
  /** Мир отдаёт накопленный урон (counters.damageDealt/damageTaken). По RL-проводу
   *  его нет: ставим 0 и не используем как сигнал (ветки политики, которые на него
   *  смотрят, просто не срабатывают — счётчики убийств при этом точны). */
  damageCounters: boolean;
  /** Мир отдаёт счётчики выполнения ПО КАЖДОЙ цели квеста. По RL-проводу видна
   *  только суммарная доля: для одноцельных квестов она пересчитывается точно,
   *  для многоцельных `have` conservatively = 0 («нужно всё»), а не выдуманное число. */
  questObjectiveCounts: boolean;
  /** Оценка задержки связи, мс (0 для in-process). */
  latencyMs: number;
}

/**
 * Минимальная поверхность мира, на которой работает весь агент.
 * Методы, требующие привилегий (countItem), обязаны бросать исключение, если
 * возможность не объявлена: молчаливый 0 вместо факта — это подделка доказательства.
 */
export interface World {
  readonly actions: readonly string[];
  readonly step: number;
  /** Причина завершения эпизода или null. */
  readonly ended: string | null;
  readonly counters: Counters;
  readonly copper: number;
  readonly capabilities: WorldCapabilities;
  /** Факты игры (obs/actions/диапазоны/классы): мир один и тот же, стенды разные. */
  readonly facts: GameFacts;

  actionIndex(name: string): number;
  /** Одно действие агента; возвращает факт изменения счётчиков. */
  stepAction(action: string | number): StepResult;
  /** Наблюдение: только то, что мир действительно показывает. */
  observe(): WorldModel;
  /** Готовность способностей (у стенда берётся из того же RL-наблюдения игры). */
  abilities(): AbilityView[];
  /** Число предметов в сумках; бросает, если itemCountApi=false. */
  countItem(itemId: string): number;
  /** Состояние квеста глазами игры ('available'|'active'|'ready'|'done'|...);
   *  бросает, если questStateApi='none'. При 'observed' возвращает только то,
   *  что различимо в наблюдении ('active'|'ready'|'done'|'other'), и НИКОГДА не
   *  утверждает 'available' — см. QuestStateAccess. */
  questState(questId: string): string;
  /** Выбрать конкретную цель (онлайн-мир: wire-команды `target`/`tab`).
   *  Отсутствует, если targetSelection='nearest-only' — тогда только target_nearest. */
  targetEntity?(id: number): void;
}

/** Человекочитаемое объявление возможностей — печатается ДО прогона. */
export function describeCapabilities(c: WorldCapabilities): string[] {
  return [
    `транспорт=${c.transport}, frameSkip=${c.frameSkip}, реальное время=${c.realtime ? 'да' : 'нет'}, другие игроки=${c.otherPlayers ? 'да' : 'нет'}, задержка=${c.latencyMs} мс`,
      `абсолютные координаты=${c.absoluteCoords ? 'да' : 'нет'}, состояние любого квеста=${c.questStateApi}, предметы в сумках=${c.itemCountApi ? 'да' : 'нет'}, данные контента=${c.contentData ? 'да' : 'нет'}, детерминизм=${c.deterministic ? 'да' : 'нет'}`,
    `выбор цели=${c.targetSelection}, сдача/отказ от квеста=${c.abandonQuest ? 'accept+turn-in+abandon' : 'только то, что даёт стенд'}, продавец=${c.vendor ? 'да' : 'нет'}, груп-лут (roll)=${c.partyLootRolls ? 'да' : 'нет'}, словарь команд=${c.commandVocabulary}`,
    `состояние квестов=${c.questStateApi}, идентичность сущностей=${c.entityIdentity}, вид сущностей (templateId)=${c.entityTemplates ? 'да' : 'нет'}, абсолютное HP сущностей=${c.entityAbsoluteHp ? 'да' : 'нет'}`,
    `счётчики урона=${c.damageCounters ? 'да' : 'нет (0, не используется как сигнал)'}, счётчики по целям квеста=${c.questObjectiveCounts ? 'да' : 'нет (доля; для многоцельных have=0 консервативно)'}`,
  ];
}
