// Факты игры: всё, что агент считает правдой о мире, держится на импорте из
// upstream (game/src/sim). Если upstream поменяет баланс или переименует контент —
// эти тесты покраснеют, и это сигнал пересмотреть политику, а не поправить тест.
// Числа здесь не захардкожены «из памяти»: они выведены из данных игры
// (антипаттерн B3 архивной fly-линии, где obs=607 был вписан руками в train.py).
import { describe, expect, it } from 'vitest';

import {
  INTEREST_DROP_RADIUS,
  allCamps,
  campsFor,
  classAbilities,
  gameFacts,
  mobLevelRange,
  mobsDropping,
  npcPins,
  questDef,
} from '../src/facts';
import { VIEW_RADIUS } from '../src/world/types';

const F = gameFacts();

describe('пространство наблюдений и действий', () => {
  it('actions согласованы с numActions и разбиением на способности', () => {
    expect(F.actions.length).toBe(F.numActions);
    expect(F.abilitySlots).toBe(F.numActions - F.nonAbilityActions.length);
    expect(F.nonAbilityActions).toContain('noop');
    expect(F.nonAbilityActions).toContain('attack');
    expect(F.nonAbilityActions).toContain('interact');
  });

  it('obs больше нуля и берётся из игры (obsSize()), а не из константы', () => {
    expect(F.obsSize).toBeGreaterThan(100);
  });

  it('боевые дистанции: melee == interact (правило игры, на нём держится навигация)', () => {
    expect(F.meleeRange).toBe(F.interactRange);
    expect(F.meleeRange).toBeGreaterThan(0);
  });

  it('классы: воин есть, у него непустой набор способностей с уникальными именами', () => {
    expect(F.classes).toContain('warrior');
    const abilities = classAbilities('warrior');
    expect(abilities.length).toBeGreaterThan(10);
    expect(new Set(abilities).size).toBe(abilities.length);
    // Самохил воина, на который опирается арбитраж (rest/flee без него невозможен).
    expect(abilities).toContain('furious_mending');
  });

  it('неизвестный класс — громкая ошибка, а не пустой набор', () => {
    expect(() => classAbilities('deathknight')).toThrow(/неизвестный класс/);
  });
});

describe('наблюдение ограничено так же, как в RL-obs игры', () => {
  it('VIEW_RADIUS не шире радиуса интереса живого мира', () => {
    expect(VIEW_RADIUS).toBeLessThanOrEqual(INTEREST_DROP_RADIUS);
  });
});

describe('контент зоны: лагеря, NPC, дроп, уровни', () => {
  it('лагеря мобов есть, у волков — своя скорость и уровень', () => {
    const camps = allCamps();
    expect(camps.length).toBeGreaterThan(100);
    const wolves = campsFor('forest_wolf');
    expect(wolves.length).toBeGreaterThan(0);
    for (const c of wolves) {
      expect(c.radius).toBeGreaterThan(0);
      expect(c.count).toBeGreaterThan(0);
      expect(Number.isFinite(c.x) && Number.isFinite(c.z)).toBe(true);
    }
  });

  it('old_greyjaw: 4-й уровень, роняет greyjaw_fang — цель q_greyjaw', () => {
    const lvl = mobLevelRange('old_greyjaw');
    expect(lvl).not.toBeNull();
    expect(lvl!.maxLevel).toBe(4);
    expect(mobsDropping('greyjaw_fang')).toContain('old_greyjaw');
    const q = questDef('q_greyjaw');
    expect(q).toBeDefined();
  });

  it('пины NPC на карте: координаты конечны, у квестодателей непустой список квестов', () => {
    const pins = npcPins();
    expect(pins.length).toBeGreaterThan(10);
    for (const p of pins) {
      expect(Number.isFinite(p.x) && Number.isFinite(p.z)).toBe(true);
      expect(Array.isArray(p.questIds)).toBe(true);
    }
    expect(pins.filter((p) => p.questIds.length > 0).length).toBeGreaterThan(1);
  });
});
