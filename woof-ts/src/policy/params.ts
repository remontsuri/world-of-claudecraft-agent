/**
 * params.ts — ЕДИНАЯ таблица настраиваемых порогов агента.
 *
 * Зачем: самоулучшение невозможно, пока пороги размазаны по модулям как
 * литералы. Здесь они собраны в один объект с объявленными диапазонами, чтобы
 * контур обучения (src/learn/tune.ts) мог предлагать значения, а прогон —
 * печатать их ДО измерения и писать в evidence (правило проекта: пороги
 * объявляются до измерения; никаких молчаливых подмен).
 *
 * Что здесь НЕ настраивается и почему:
 *   - VIEW_RADIUS=60 — не порог, а факт соответствия RL-наблюдению игры
 *     (obs.ts: d < 60); менять его значит сравнивать разные миры;
 *   - MELEE_RANGE/INTERACT_RANGE/TURN_SPEED/RUN_SPEED — константы игры,
 *     импортируются из дерева игры (src/sim/types.ts), а не подбираются;
 *   - npcViewRadius — политика наблюдения, задаётся флагом --npc-view и
 *     объявляется отдельно (см. run.ts и ONLINE-WORLD.md).
 *
 * Загрузка: только WOOF_PARAMS=<file.json> (переменная окружения). Флаг --params
 * невозможен в принципе: статические импорты ESM поднимаются до разбора argv,
 * поэтому PARAMS читается при импорте модуля, а каждый прогон изолирован —
 * тюнинг обязан гонять кандидатов отдельными процессами (см. src/learn/tune.ts).
 * Неизвестный ключ, выход за диапазон, не-число или не кратное шагу значение —
 * исключение, а не «подгонка под ближайшее».
 */
import { readFileSync } from 'node:fs';

export interface ParamSpec {
  key: string;
  def: number;
  min: number;
  max: number;
  step: number;
  group: 'combat' | 'survival' | 'navigation' | 'arbitration' | 'quest';
  note: string;
}

export const PARAM_SPECS: ParamSpec[] = [
  // --- бой -------------------------------------------------------------------
  { key: 'combatMaxActions', def: 64, min: 12, max: 160, step: 4, group: 'combat', note: 'бюджет боя в действиях мира (0.25 с каждое); замах ~2 с' },
  { key: 'approachStop', def: 4.0, min: 2, max: 5, step: 0.5, group: 'combat', note: 'ярды: насколько близко подходить к цели (MELEE_RANGE=5)' },
  { key: 'turnTolerance', def: 0.35, min: 0.1, max: 0.8, step: 0.05, group: 'combat', note: 'рад: допустимое отклонение цели от курса перед ударом' },
  { key: 'faceMaxActions', def: 6, min: 2, max: 12, step: 1, group: 'combat', note: 'сколько действий на доворот к цели' },
  { key: 'approachRetry', def: 8, min: 2, max: 24, step: 2, group: 'combat', note: 'бюджет повторного подхода внутри боя' },
  { key: 'unkillableHpFactor', def: 5, min: 2, max: 20, step: 1, group: 'combat', note: 'цель с HP больше N× наших не считается убиваемой (манекен 999999 HP)' },
  { key: 'engageRadius', def: 18, min: 6, max: 40, step: 2, group: 'combat', note: 'ярды: радиус поиска «соседей» цели перед началом боя' },
  { key: 'engageMaxNeighbours', def: 1, min: 0, max: 3, step: 1, group: 'combat', note: 'сколько соседей у цели ещё допускает бой 1×1' },
  { key: 'farmTriggerDist', def: 25, min: 5, max: 60, step: 5, group: 'combat', note: 'ярды: доступного по уровню моба на этой дистанции арбитраж уже бьёт' },

  // --- выживание -------------------------------------------------------------
  { key: 'lowHpAbort', def: 0.55, min: 0.2, max: 0.9, step: 0.05, group: 'survival', note: 'доля HP, ниже которой прерываем бой (мобы быстрее игрока)' },
  { key: 'crowdAbortHp', def: 0.75, min: 0.4, max: 1.0, step: 0.05, group: 'survival', note: 'доля HP для выхода из боя, если в него втянулась стая' },
  { key: 'crowdLimitFarm', def: 2, min: 1, max: 4, step: 1, group: 'survival', note: 'сколько агрессоров на нас — новый бой не начинаем' },
  { key: 'healMaxActions', def: 40, min: 8, max: 120, step: 4, group: 'survival', note: 'бюджет отдыха/регена в действиях мира' },
  { key: 'healTarget', def: 0.95, min: 0.6, max: 1.0, step: 0.05, group: 'survival', note: 'до какой доли HP отдыхаем' },
  { key: 'healThreatDist', def: 14, min: 4, max: 40, step: 2, group: 'survival', note: 'ярды: агрессор ближе — не отдыхаем, а отходим' },
  { key: 'fleeMaxActions', def: 24, min: 6, max: 80, step: 2, group: 'survival', note: 'бюджет отхода в действиях мира' },
  { key: 'fleeTurnMax', def: 6, min: 2, max: 12, step: 1, group: 'survival', note: 'сколько действий на разворот от угрозы/к убежищу' },
  { key: 'fleeSafeDist', def: 25, min: 10, max: 60, step: 5, group: 'survival', note: 'ярды: отрыв дальше этой дистанции считаем успешным' },
  { key: 'havenDist', def: 160, min: 40, max: 400, step: 20, group: 'survival', note: 'ярды: ближайший городской NPC в этом радиусе — убежище' },
  { key: 'respawnWaitActions', def: 80, min: 20, max: 200, step: 10, group: 'survival', note: 'сколько действий мира ждём воскрешения (respawnSeconds=15)' },
  { key: 'critHp', def: 0.15, min: 0.05, max: 0.4, step: 0.05, group: 'survival', note: 'аварийный порог HP (порт Java-линии)' },
  { key: 'lowHp', def: 0.3, min: 0.1, max: 0.6, step: 0.05, group: 'survival', note: 'низкий HP: бежать/лечиться (порт Java-линии)' },
  { key: 'crowdRadius', def: 18, min: 6, max: 40, step: 2, group: 'survival', note: 'ярды: кого считаем «рядом» при оценке толпы' },
  { key: 'crowdLimit', def: 2, min: 1, max: 5, step: 1, group: 'survival', note: 'сколько агрессоров уже толпа' },
  { key: 'fleeTriggerDist', def: 25, min: 10, max: 60, step: 5, group: 'survival', note: 'ярды: дальше угрозы бежать бессмысленно, надо лечиться' },

  // --- навигация -------------------------------------------------------------
  { key: 'navMaxSteps', def: 80, min: 20, max: 200, step: 10, group: 'navigation', note: 'бюджет подхода к цели в действиях мира' },
  { key: 'searchActions', def: 12, min: 2, max: 40, step: 2, group: 'navigation', note: 'действий на поиск на месте (пришли, а цели не видно)' },
  { key: 'unstuckMinMove', def: 0.4, min: 0.1, max: 1.5, step: 0.1, group: 'navigation', note: 'ярдов: меньшее смещение за действие = упёрлись в геометрию' },

  // --- арбитраж --------------------------------------------------------------
  { key: 'loopThreshold', def: 6, min: 2, max: 20, step: 1, group: 'arbitration', note: 'сколько одинаковых решений подряд считаем петлёй' },
  { key: 'failLimit', def: 3, min: 1, max: 10, step: 1, group: 'arbitration', note: 'сколько провалов навыка подряд ведут на перерыв' },
  { key: 'failCooldown', def: 12, min: 2, max: 60, step: 2, group: 'arbitration', note: 'длительность перерыва навыка в решениях' },
  { key: 'healBelow', def: 0.95, min: 0.5, max: 1.0, step: 0.05, group: 'arbitration', note: 'ниже этой доли HP арбитраж рассматривает лечение' },

  // --- квесты ----------------------------------------------------------------
  { key: 'levelDeltaMax', def: 1, min: 0, max: 3, step: 1, group: 'quest', note: 'на сколько уровней выше нас моб, с которым мы готовы драться' },
  { key: 'giverFailExhaust', def: 3, min: 1, max: 10, step: 1, group: 'quest', note: 'сколько подряд неудачных попыток взять квест у одного NPC, после чего он считается бесполезным (квесты, закрытые по классу/пререквизиту, по проводу неразличимы — учится на провалах)' },
];

export type Params = Record<string, number>;

export const DEFAULT_PARAMS: Params = Object.fromEntries(PARAM_SPECS.map((s) => [s.key, s.def]));

const SPEC_BY_KEY: Map<string, ParamSpec> = new Map(PARAM_SPECS.map((s) => [s.key, s]));

/** Загрузить параметры: базовые значения + переопределения из файла.
 *  Неизвестный ключ / выход за диапазон / не кратный шагу — исключение. */
export function loadParams(file?: string | null): Params {
  const out: Params = { ...DEFAULT_PARAMS };
  const path = file ?? process.env.WOOF_PARAMS ?? null;
  if (!path) return out;
  const raw = JSON.parse(readFileSync(path, 'utf8')) as Record<string, unknown>;
  const overrides = (raw.params ?? raw) as Record<string, unknown>;
  for (const [k, v] of Object.entries(overrides)) {
    const spec = SPEC_BY_KEY.get(k);
    if (!spec) throw new Error(`неизвестный параметр "${k}" (нет в PARAM_SPECS) — молча игнорировать не будем`);
    if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error(`параметр "${k}" должен быть конечным числом, получено ${JSON.stringify(v)}`);
    if (v < spec.min || v > spec.max) throw new Error(`параметр "${k}=${v}" вне объявленного диапазона [${spec.min}, ${spec.max}]`);
    // Кратность шагу: контур обучения предлагает значения из объявленной сетки,
    // а не «ближайшее похожее». Без этой проверки таблица диапазонов врала бы
    // о том, какие значения вообще рассматриваются.
    const steps = (v - spec.min) / spec.step;
    if (Math.abs(steps - Math.round(steps)) > 1e-9) {
      throw new Error(
        `параметр "${k}=${v}" не кратен шагу ${spec.step} от min ${spec.min} — объявленная сетка значений нарушена`,
      );
    }
    out[k] = v;
  }
  return out;
}

/** Действующий набор параметров процесса: читается один раз при старте,
 *  поэтому каждый прогон изолирован (тюнинг гоняет кандидатов отдельными процессами). */
export const PARAMS: Params = loadParams();

/** Какие параметры отличаются от базовых — печатается до прогона и пишется в evidence. */
export function diffFromDefaults(p: Params = PARAMS): Record<string, { from: number; to: number }> {
  const out: Record<string, { from: number; to: number }> = {};
  for (const s of PARAM_SPECS) if (p[s.key] !== s.def) out[s.key] = { from: s.def, to: p[s.key] };
  return out;
}
