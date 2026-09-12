package com.woof.agent.fsm;

/**
 * Quest FSM — states and transitions.
 * Invariant: qs == ACTIVE => accept_quest = INVALID
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

    public QuestState getCurrent() { return current; }
    public void transition(QuestState newState) { this.current = newState; }

    public boolean isObjectivePhase() {
        return current == QuestState.DO_OBJECTIVE || current == QuestState.VERIFY_PROGRESS;
    }
}
