package com.woof.agent.fsm;

import com.woof.agent.env.Entity;
import com.woof.agent.env.QuestEntry;
import com.woof.agent.env.WorldState;

/**
 * Quest FSM — состояния и переходы.
 * Инвариант: qs == ACTIVE => accept_quest = INVALID
 *
 * Фаза ВЫВОДИТСЯ из наблюдения (syncFrom), а не переключается вручную в
 * исполнителе навыка: иначе гейты фаз работают по устаревшему состоянию.
 */
public class GoalFSM {
    public enum QuestState {
        QUEST_NONE,
        FIND_GIVER,
        ACCEPT,
        VERIFY_ACCEPT,
        DO_OBJECTIVE,
        VERIFY_PROGRESS,
        RETURN_TO_GIVER,
        TURN_IN,
        VERIFY_TURN_IN,
        QUEST_COMPLETE
    }

    private QuestState current = QuestState.QUEST_NONE;
    private String currentQuestId = null;
    private int completions = 0;

    public QuestState getCurrent() { return current; }
    public String getCurrentQuestId() { return currentQuestId; }
    public int getCompletions() { return completions; }
    public void transition(QuestState newState) { this.current = newState; }

    public boolean isObjectivePhase() {
        return current == QuestState.DO_OBJECTIVE || current == QuestState.VERIFY_PROGRESS;
    }

    /**
     * Вывести фазу из снимка мира.
     *  готов к сдаче + NPC в радиусе  -> TURN_IN
     *  готов к сдаче                  -> RETURN_TO_GIVER
     *  активный квест                 -> DO_OBJECTIVE
     *  NPC с квестом рядом            -> FIND_GIVER
     *  иначе                          -> QUEST_NONE
     */
    public QuestState syncFrom(WorldState ws) {
        if (ws == null) return current;
        QuestEntry ready = ws.readyQuest();
        QuestEntry active = ws.activeQuest();
        Entity giver = ws.questGiverInRange();

        QuestState prev = current;
        if (ready != null) {
            currentQuestId = ready.id;
            current = (giver != null) ? QuestState.TURN_IN : QuestState.RETURN_TO_GIVER;
        } else if (active != null) {
            currentQuestId = active.id;
            current = QuestState.DO_OBJECTIVE;
        } else if (giver != null) {
            currentQuestId = null;
            current = QuestState.FIND_GIVER;
        } else {
            if (prev == QuestState.TURN_IN || prev == QuestState.RETURN_TO_GIVER) {
                completions++;              // сдача подтверждена: квест ушёл из ready
            }
            currentQuestId = null;
            current = QuestState.QUEST_NONE;
        }
        return current;
    }
}
