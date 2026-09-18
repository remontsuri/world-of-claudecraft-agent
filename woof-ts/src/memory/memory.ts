/**
 * memory.ts — порт memory/WorldMemory.java: что агент запомнил о мире.
 *
 * Память нужна потому, что наблюдение ограничено радиусом (VIEW_RADIUS):
 * координаты выдающего NPC и цели квеста, увиденные один раз, приходится хранить.
 */
export interface Coord {
  x: number;
  z: number;
}

export class WorldMemory {
  /** questId -> координаты NPC, который даёт/принимает квест. */
  readonly questGivers = new Map<string, Coord>();
  /** Координаты живых мобов — целей квеста (questId -> точка). */
  private readonly questMobCoords = new Map<string, Coord>();
  /** Посещённые точки (сетка 10x10 ярдов) — чтобы не крутиться на месте. */
  readonly visited = new Set<string>();
  /** Последние действия (не более 100) — журнал и поиск зацикливания. */
  readonly recentActions: string[] = [];
  /** Шаблон моба -> где его видели в последний раз. */
  readonly mobSpots = new Map<string, Coord>();
  /** NPC, у которого для нас ничего нет (закрыто по классу/пререквизиту) — не возвращаемся. */
  readonly exhaustedGivers = new Set<string>();

  markGiverExhausted(templateId: string): void {
    this.exhaustedGivers.add(templateId);
  }

  isGiverExhausted(templateId: string): boolean {
    return this.exhaustedGivers.has(templateId);
  }

  rememberGiver(key: string, c: Coord): void {
    this.questGivers.set(key, c);
  }

  giverLocation(key: string): Coord | null {
    return this.questGivers.get(key) ?? null;
  }

  saveQuestMobCoord(questId: string, c: Coord): void {
    this.questMobCoords.set(questId, c);
  }

  /** Снять устаревшую координату цели квеста (пришли — а моба там нет). */
  forgetQuestMob(questId: string): void {
    this.questMobCoords.delete(questId);
  }

  questMobCoord(questId: string): Coord | null {
    return this.questMobCoords.get(questId) ?? null;
  }

  saveMobSpot(templateId: string, c: Coord): void {
    this.mobSpots.set(templateId, c);
  }

  mobSpot(templateId: string): Coord | null {
    return this.mobSpots.get(templateId) ?? null;
  }

  markVisited(x: number, z: number): void {
    this.visited.add(`${Math.round(x / 10)}:${Math.round(z / 10)}`);
  }

  wasVisited(x: number, z: number): boolean {
    return this.visited.has(`${Math.round(x / 10)}:${Math.round(z / 10)}`);
  }

  recordAction(action: string): void {
    this.recentActions.push(action);
    if (this.recentActions.length > 100) this.recentActions.shift();
  }
}

/** Учёт навыков (порт memory/SkillLibrary: сколько раз вызван, сколько раз удался). */
export interface SkillStats {
  uses: number;
  successes: number;
  lastResult: string;
}

export class SkillLibrary {
  private readonly stats = new Map<string, SkillStats>();

  record(skill: string, ok: boolean, result: string): void {
    const s = this.stats.get(skill) ?? { uses: 0, successes: 0, lastResult: '' };
    s.uses++;
    if (ok) s.successes++;
    s.lastResult = result;
    this.stats.set(skill, s);
  }

  get(skill: string): SkillStats | null {
    return this.stats.get(skill) ?? null;
  }

  snapshot(): Record<string, SkillStats> {
    return Object.fromEntries([...this.stats.entries()].sort((a, b) => a[0].localeCompare(b[0])));
  }
}
