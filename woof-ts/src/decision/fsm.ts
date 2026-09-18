/**
 * fsm.ts — порт fsm/GoalFSM.java: состояния квестового цикла.
 *
 * Инвариант тот же: фаза ВЫВОДИТСЯ из наблюдения (syncFrom), а не переключается
 * вручную в исполнителе — иначе гейты фаз работают по устаревшему состоянию.
 */
import {
  availableGiverInRange,
  type EntityView,
  type QuestView,
  activeQuest,
  readyQuest,
  turnInNpcInRange,
  type WorldModel,
} from '../world/types';

export type QuestPhase =
  | 'QUEST_NONE'
  | 'FIND_GIVER'
  | 'ACCEPT'
  | 'VERIFY_ACCEPT'
  | 'DO_OBJECTIVE'
  | 'VERIFY_PROGRESS'
  | 'RETURN_TO_GIVER'
  | 'TURN_IN'
  | 'VERIFY_TURN_IN'
  | 'QUEST_COMPLETE';

export class GoalFSM {
  private current: QuestPhase = 'QUEST_NONE';
  private currentQuestId: string | null = null;
  private completions = 0;
  private lastProgress = -1;

  get phase(): QuestPhase {
    return this.current;
  }

  get questId(): string | null {
    return this.currentQuestId;
  }

  /** Сколько раз квест уходил из ready — подтверждённые сдачи. */
  get completionCount(): number {
    return this.completions;
  }

  transition(next: QuestPhase): void {
    this.current = next;
  }

  isObjectivePhase(): boolean {
    return this.current === 'DO_OBJECTIVE' || this.current === 'VERIFY_PROGRESS';
  }

  /**
   * Вывести фазу из снимка мира:
   *   готов к сдаче + принимающий NPC в радиусе -> TURN_IN
   *   готов к сдаче                             -> RETURN_TO_GIVER
   *   активный квест                            -> DO_OBJECTIVE (VERIFY_PROGRESS, если прогресс вырос)
   *   NPC с ДОСТУПНЫМ квестом рядом             -> FIND_GIVER
   *   иначе                                     -> QUEST_NONE
   */
  syncFrom(w: WorldModel, interactRange: number): QuestPhase {
    const ready: QuestView | null = readyQuest(w);
    const active: QuestView | null = activeQuest(w);
    const turnInNpc: EntityView | null = turnInNpcInRange(w, ready, interactRange);
    const giver: EntityView | null = availableGiverInRange(w, interactRange);
    const prev = this.current;

    if (ready) {
      this.currentQuestId = ready.id;
      this.current = turnInNpc ? 'TURN_IN' : 'RETURN_TO_GIVER';
    } else if (active) {
      this.currentQuestId = active.id;
      const progress = active.progress;
      this.current =
        prev === 'DO_OBJECTIVE' && progress > this.lastProgress ? 'VERIFY_PROGRESS' : 'DO_OBJECTIVE';
      this.lastProgress = progress;
    } else if (giver) {
      this.currentQuestId = null;
      this.current = 'FIND_GIVER';
      this.lastProgress = -1;
    } else {
      if (prev === 'TURN_IN' || prev === 'RETURN_TO_GIVER') {
        this.completions++; // сдача подтверждена: квест ушёл из ready
      }
      this.currentQuestId = null;
      this.current = 'QUEST_NONE';
      this.lastProgress = -1;
    }
    return this.current;
  }
}
