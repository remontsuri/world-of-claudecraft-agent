// Таблица порогов — фундамент самоулучшения: контур обучения предлагает значения,
// прогон печатает их ДО измерения и пишет в evidence. Здесь проверяем, что таблица
// не врёт: диапазоны осмысленны, базовые значения в них лежат и кратны шагу,
// а загрузка строга (опечатка или выход за сетку — исключение, не молчаливый
// «ближайший подходящий»).
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { DEFAULT_PARAMS, PARAM_SPECS, diffFromDefaults, loadParams } from '../src/policy/params';

const paramsFile = (obj: unknown): string => {
  const dir = mkdtempSync(join(tmpdir(), 'woof-params-'));
  const file = join(dir, 'params.json');
  writeFileSync(file, JSON.stringify(obj));
  return file;
};

describe('объявленная таблица', () => {
  it('порогов достаточно, чтобы что-то улучшать, и ключи уникальны', () => {
    expect(PARAM_SPECS.length).toBeGreaterThan(25);
    const keys = PARAM_SPECS.map((s) => s.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('у каждого порога min < def < max, шаг > 0, группа и пояснение заполнены', () => {
    for (const s of PARAM_SPECS) {
      expect(s.min, `${s.key}.min`).toBeLessThan(s.max);
      expect(s.def, `${s.key}.def >= min`).toBeGreaterThanOrEqual(s.min);
      expect(s.def, `${s.key}.def <= max`).toBeLessThanOrEqual(s.max);
      expect(s.step, `${s.key}.step`).toBeGreaterThan(0);
      expect(s.group, `${s.key}.group`).toMatch(/combat|survival|navigation|arbitration|quest/);
      expect(s.note.length, `${s.key}.note`).toBeGreaterThan(10);
    }
  });

  it('базовое значение кратно шагу от min (иначе сетка недостижима для def)', () => {
    for (const s of PARAM_SPECS) {
      const steps = (s.def - s.min) / s.step;
      expect(Math.abs(steps - Math.round(steps)), `${s.key} def=${s.def} min=${s.min} step=${s.step}`).toBeLessThan(1e-9);
    }
  });

  it('DEFAULT_PARAMS — ровно def из таблицы, без лишних ключей', () => {
    expect(Object.keys(DEFAULT_PARAMS).sort()).toEqual(PARAM_SPECS.map((s) => s.key).sort());
    for (const s of PARAM_SPECS) expect(DEFAULT_PARAMS[s.key]).toBe(s.def);
  });

  it('все группы представлены (тюнинг может идти по группам)', () => {
    const groups = new Set(PARAM_SPECS.map((s) => s.group));
    expect(groups.size).toBeGreaterThanOrEqual(4);
  });
});

describe('загрузка переопределений', () => {
  it('без файла — базовые значения', () => {
    expect(loadParams(null)).toEqual(DEFAULT_PARAMS);
  });

  it('валидное переопределение применяется, остальные остаются базовыми', () => {
    const p = loadParams(paramsFile({ levelDeltaMax: 0, engageRadius: 24 }));
    expect(p.levelDeltaMax).toBe(0);
    expect(p.engageRadius).toBe(24);
    expect(p.lowHpAbort).toBe(DEFAULT_PARAMS.lowHpAbort);
  });

  it('обёртка { params: {...} } тоже принимается', () => {
    const p = loadParams(paramsFile({ params: { levelDeltaMax: 2 } }));
    expect(p.levelDeltaMax).toBe(2);
  });

  it('неизвестный ключ — исключение (опечатка не должна молча ничего не менять)', () => {
    expect(() => loadParams(paramsFile({ lowHpAborrt: 0.5 }))).toThrow(/неизвестный параметр/);
  });

  it('значение вне диапазона — исключение', () => {
    const spec = PARAM_SPECS.find((s) => s.key === 'lowHpAbort')!;
    expect(() => loadParams(paramsFile({ lowHpAbort: spec.max + spec.step }))).toThrow(/вне объявленного диапазона/);
    expect(() => loadParams(paramsFile({ lowHpAbort: spec.min - spec.step }))).toThrow(/вне объявленного диапазона/);
  });

  it('значение не из сетки шага — исключение', () => {
    const spec = PARAM_SPECS.find((s) => s.key === 'engageRadius')!;
    expect(() => loadParams(paramsFile({ engageRadius: spec.min + spec.step / 2 }))).toThrow(/не кратен шагу/);
  });

  it('не-число — исключение', () => {
    expect(() => loadParams(paramsFile({ levelDeltaMax: '1' }))).toThrow(/конечным числом/);
    expect(() => loadParams(paramsFile({ levelDeltaMax: null }))).toThrow(/конечным числом/);
  });

  it('несуществующий файл — исключение, а не тихий возврат базовых', () => {
    expect(() => loadParams('/нет/такого/файла.json')).toThrow();
  });
});

describe('дифф от базовых (печатаем до прогона, пишем в evidence)', () => {
  it('для базовых — пусто', () => {
    expect(diffFromDefaults(DEFAULT_PARAMS)).toEqual({});
  });

  it('для переопределённых — from/to', () => {
    const p = loadParams(paramsFile({ levelDeltaMax: 0, crowdLimit: 3 }));
    expect(diffFromDefaults(p)).toEqual({
      levelDeltaMax: { from: DEFAULT_PARAMS.levelDeltaMax, to: 0 },
      crowdLimit: { from: DEFAULT_PARAMS.crowdLimit, to: 3 },
    });
  });
});
