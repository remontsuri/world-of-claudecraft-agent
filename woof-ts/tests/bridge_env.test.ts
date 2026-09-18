// Бридж к headless env server игры: проверка НА ЖИВОМ процессе upstream.
//
// Главный тест здесь — эквивалентность: тот же сид и та же последовательность
// действий обязаны дать тот же мир, что и in-process стенд (SimWorld). Если
// декодер obs ошибся хотя бы в смещении поля, счётчики/координаты/дистанции
// разъедутся, и тест покраснеет. Это ровно тот класс дефектов, который уже стоил
// нам ложно-зелёных прогонов (захардкоженный obs=607 в архивной fly-линии, баг B3).
//
// Второй по важности — честность ограничений: по проводу нет id/вида сущностей и
// состояния 'available', и тесты фиксируют, что бридж в этих местах НЕ угадывает.
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, describe, expect, it } from 'vitest';

import { EnvClient } from '../src/bridge/env_client';
import { NdjsonBridge } from '../src/bridge/ndjson_bridge';
import { decodeObs, obsLayout } from '../src/bridge/obs';
import { buildAgent, unsupportedReasons } from '../src/core/build';
import { gameFacts } from '../src/facts';
import { SimWorld } from '../src/world/sim_world';
import { VIEW_RADIUS } from '../src/world/types';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SERVER = join(ROOT, 'dist-env/env_server.cjs');
const F = gameFacts();

const spec = () => ({ command: process.execPath, args: [SERVER], cwd: ROOT });

/** Мир — это целый процесс (или in-process Sim): держать их живыми до afterAll
 *  нельзя, на 2 ГБ RAM это OOM-kill. Поэтому каждый тест создаёт мир через
 *  withBridge/withClient и закрывает его сразу, в finally. */
function withBridge<T>(seed: number, fn: (b: NdjsonBridge) => T): T {
  const b = new NdjsonBridge({ seed, playerClass: 'warrior', frameSkip: 5, spec: spec() });
  try {
    return fn(b);
  } finally {
    b.close();
  }
}

function withClient<T>(fn: (c: EnvClient) => T): T {
  const c = EnvClient.spawn({ spec: spec() });
  try {
    return fn(c);
  } finally {
    c.close();
  }
}

beforeAll(() => {
  if (!existsSync(SERVER)) {
    // Тесты самодостаточны: собираем env server upstream нашим esbuild,
    // если его ещё нет (tools/build_env.sh, ~1 с, дерево игры не меняем).
    execFileSync('bash', [join(ROOT, 'tools/build_env.sh')], { stdio: 'inherit' });
  }
});


const makeSim = (seed = 42) =>
  SimWorld.create({
    seed,
    playerClass: 'warrior',
    npcViewRadius: VIEW_RADIUS,
    gathererIdentity: { kind: 'headless', id: `hl:woof-ts:test:${seed}` },
  });


describe('раскладка obs выводится из фактов игры', () => {
  it('вычисленная длина совпадает с obsSize(), слоты мобов целые', () => {
    const L = obsLayout(F);
    expect(L.total).toBe(F.obsSize);
    expect(L.nearbyMobSlots).toBeGreaterThan(0);
    expect(Number.isInteger(L.nearbyMobSlots)).toBe(true);
    expect(L.abilitySlots).toBe(F.abilitySlots);
  });

  it('obs другой длины — исключение, а не «прочитали что смогли»', () => {
    expect(() => decodeObs(new Array(F.obsSize - 1).fill(0))).toThrow(/длины/);
  });
});

describe('контракт env server (NDJSON)', () => {
  it('info отдаёт те же размеры и словарь действий, что и дерево игры', () => {
    withClient((client) => {
      expect(client.info.obs_size).toBe(F.obsSize);
      expect(client.info.num_actions).toBe(F.numActions);
      expect(client.info.actions).toEqual([...F.actions]);
      expect(client.alive).toBe(true);
    });
  });

  it('действие вне словаря — отказ мира, а не тихий noop', () => {
    withClient((client) => {
      client.reset({ seed: 42, playerClass: 'warrior' });
      expect(() => client.step(9999)).toThrow(/мир отказал|error/i);
    });
  });

  it('после close мир не отвечает (канал закрыт)', () => {
    const client = EnvClient.spawn({ spec: spec() });
    client.close();
    expect(client.alive).toBe(false);
    expect(() => client.step(0)).toThrow(/закрыт|завершился/);
  });
});

describe('эквивалентность бриджа и стенда: один и тот же мир', () => {
  const seq = [
    'forward', 'forward', 'turn_left', 'forward', 'target_nearest',
    'attack', 'attack', 'ability_1', 'attack', 'interact',
    'forward', 'forward', 'target_nearest', 'attack', 'attack',
    'attack', 'attack', 'ability_2', 'noop', 'forward',
    'target_nearest', 'attack', 'attack', 'interact', 'forward',
  ] as const;

  it('стартовое состояние совпадает: координаты, уровень, HP', () => {
    const sim = makeSim();
    withBridge(42, (bridge) => {
    const a = sim.observe();
    const b = bridge.observe();
    expect(b.player.level).toBe(a.player.level);
    expect(b.player.hp).toBeCloseTo(a.player.hp, 6);
    expect(b.player.maxHp).toBeCloseTo(a.player.maxHp, 6);
    expect(b.player.x).toBeCloseTo(a.player.x, 6);
    expect(b.player.z).toBeCloseTo(a.player.z, 6);
    expect(b.player.dead).toBe(a.player.dead);
    expect(b.player.inCombat).toBe(a.player.inCombat);
    });
  });

  it('шаг за шагом совпадают счётчики, HP, координаты и ближайшие мобы', () => {
    const sim = makeSim();
    withBridge(42, (bridge) => {
    for (const action of seq) {
      const rs = sim.stepAction(action);
      const rb = bridge.stepAction(action);
      const a = sim.observe();
      const b = bridge.observe();

      expect(rb.counters.kills, `kills после ${action}`).toBe(rs.counters.kills);
      expect(rb.counters.deaths, `deaths после ${action}`).toBe(rs.counters.deaths);
      expect(rb.counters.questsCompleted, `quests после ${action}`).toBe(rs.counters.questsCompleted);
      expect(b.player.hp, `hp после ${action}`).toBeCloseTo(a.player.hp, 5);
      expect(b.player.x, `x после ${action}`).toBeCloseTo(a.player.x, 5);
      expect(b.player.z, `z после ${action}`).toBeCloseTo(a.player.z, 5);
      expect(b.player.level).toBe(a.player.level);
      expect(b.player.inCombat, `inCombat после ${action}`).toBe(a.player.inCombat);

      // Ближайшие враждебные мобы: obs кодирует до 5 штук в радиусе 60 ярдов.
      const expected = a.nearby.slice(0, 5);
      expect(b.nearby.length, `число мобов после ${action}`).toBe(expected.length);
      expected.forEach((e, i) => {
        expect(b.nearby[i].dist, `дистанция моба ${i} после ${action}`).toBeCloseTo(e.dist, 4);
        expect(b.nearby[i].level - b.player.level).toBe(e.level - a.player.level);
      });
    }
    });
  });

  it('готовность способностей совпадает с стендом (слот → id из набора класса)', () => {
    const sim = makeSim();
    withBridge(42, (bridge) => {
    for (const action of ['forward', 'target_nearest', 'attack', 'ability_1']) {
      sim.stepAction(action);
      bridge.stepAction(action);
    }
    const a = sim.abilities();
    const b = bridge.abilities();
    expect(b.length).toBe(a.length);
    for (let i = 0; i < a.length; i++) {
      expect(b[i].id, `слот ${i}`).toBe(a[i].id);
      expect(b[i].ready, `готовность ${a[i].id}`).toBe(a[i].ready);
      expect(b[i].cooldownFrac, `кулдаун ${a[i].id}`).toBeCloseTo(a[i].cooldownFrac, 6);
    }
    });
  });
});

describe('честность ограничений бриджа (не угадываем)', () => {
  it('возможности объявлены как у мира за проводом, а не как у стенда', () => {
    const c = withBridge(42, (b) => b.capabilities);
    expect(c.transport).toBe('ndjson-stdio');
    expect(c.entityIdentity).toBe('slot');
    expect(c.entityTemplates).toBe(false);
    expect(c.entityAbsoluteHp).toBe(false);
    expect(c.questStateApi).toBe('observed');
    expect(c.itemCountApi).toBe(false);
    expect(c.damageCounters).toBe(false);
    expect(c.questObjectiveCounts).toBe(false);
    expect(c.absoluteCoords).toBe(true); // координаты игрока из obs восстанавливаются
  });

  it('состояние квеста: active/ready/done различимы, available — нет (и это заявлено)', () => {
    const sim = makeSim();
    withBridge(42, (bridge) => {
    // Стенд знает «квест доступен»; бридж по проводу видит ноль, который
    // неразличим между available и none, поэтому возвращает 'other'.
    expect(sim.questState('q_wolves')).toBe('available');
    expect(bridge.questState('q_wolves')).toBe('other');
    // Незнакомый id — громкая ошибка, а не «other»: иначе опечатка в политике
    // выглядела бы как «квест не доступен» и агент молча шёл бы дальше.
    expect(() => bridge.questState('нет_такого_квеста')).toThrow(/нет квеста/);
    // После принятия квеста состояние видно уже точно.
    sim.stepAction('noop');
    bridge.stepAction('noop');
    expect(['active', 'ready', 'done', 'other']).toContain(bridge.questState('q_wolves'));
    });
  });

  it('countItem бросает: содержимое сумок по проводу не отдаётся', () => {
    withBridge(42, (b) => expect(() => b.countItem('greyjaw_fang')).toThrow(/itemCountApi=false/));
  });

  it('id сущностей синтетические и отрицательные: их нельзя спутать с настоящими', () => {
    withBridge(42, (bridge) => {
    for (let i = 0; i < 6; i++) bridge.stepAction('forward');
    bridge.stepAction('target_nearest');
    const m = bridge.observe();
    for (const e of [...m.nearby, ...m.corpses, ...m.objects, ...m.npcs]) expect(e.id).toBeLessThan(0);
    if (m.target) expect(m.target.id).toBeLessThan(0);
    });
  });

  it('вид сущности неизвестен: templateId пустой, а не выдуманный', () => {
    withBridge(42, (bridge) => {
      for (let i = 0; i < 4; i++) bridge.stepAction('forward');
      bridge.stepAction('target_nearest');
      for (const e of bridge.observe().nearby) expect(e.templateId).toBe('');
    });
  });

  it('слой карты на месте: пины NPC из контент-данных игры', () => {
    const m = withBridge(42, (b) => b.observe());
    expect(m.mapPins.length).toBeGreaterThan(0);
    for (const p of m.mapPins) expect(Number.isFinite(p.dist)).toBe(true);
  });

  it('урон по проводу не отдаётся: counters.damageDealt = 0, а не оценка', () => {
    // Сначала убеждаемся, что урон вообще измеряем: агент на стенде за ~14 решений
    // доходит до манекена (стартовый квест) и наносит урон. Без этой проверки тест
    // мерил бы пустоту и «совпадение нулей» сошло бы за доказательство.
    const sim = makeSim();
    const { agent } = buildAgent(sim, {
      verbose: false,
      quiet: true,
      log: () => {},
      unsupportedSkills: Object.keys(unsupportedReasons('warrior')),
    });
    agent.run(14);
    expect(sim.counters.damageDealt).toBeGreaterThan(0);

    // Бридж в тех же условиях урон не отдаёт: по проводу его нет, и мы не
    // подставляем оценку. Политика опирается на kills (он точный) и на долю HP.
    withBridge(42, (bridge) => {
      for (let i = 0; i < 8; i++) bridge.stepAction(i % 2 === 0 ? 'target_nearest' : 'attack');
      expect(bridge.capabilities.damageCounters).toBe(false);
      expect(bridge.counters.damageDealt).toBe(0);
      expect(bridge.counters.damageTaken).toBe(0);
      expect(bridge.counters.kills).toBe(0);
    });
  });
});
