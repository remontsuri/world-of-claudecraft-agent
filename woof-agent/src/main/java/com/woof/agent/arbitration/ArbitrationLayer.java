package com.woof.agent.arbitration;

import com.woof.agent.fsm.GoalFSM;
import com.woof.agent.memory.WorldMemory;
import com.woof.agent.env.WorldState;
import java.util.*;

/**
 * ArbitrationLayer — decides which skill to execute.
 * PHASE_ALLOWED gates, survival gate, infinite loop detection.
 */
public class ArbitrationLayer {
    private final GoalFSM fsm;
    private final WorldMemory memory;

    // Phase-allowed gates (from Python policy.py)
    private static final Map<String, List<String>> PHASE_ALLOWED = new HashMap<>();
    static {
        PHASE_ALLOWED.put("NO_QUEST", Arrays.asList("accept_quest", "farm", "explore"));
        PHASE_ALLOWED.put("FIND_GIVER", Arrays.asList("accept_quest", "explore"));
        PHASE_ALLOWED.put("ACCEPT", Arrays.asList("accept_quest"));
        PHASE_ALLOWED.put("DO_OBJECTIVE", Arrays.asList("farm", "navigate", "return_to_giver",
                "flee", "turn_in", "heal", "gather", "loot", "explore", "sell", "buy",
                "craft", "cast_frostbolt", "cast_fireball"));
        PHASE_ALLOWED.put("RETURN_TO_GIVER", Arrays.asList("return_to_giver", "turn_in", "flee"));
        PHASE_ALLOWED.put("TURN_IN", Arrays.asList("turn_in", "return_to_giver", "sell", "flee"));
        PHASE_ALLOWED.put("SELL_REPAIR", Arrays.asList("sell", "buy"));
        PHASE_ALLOWED.put("HEAL", Arrays.asList("heal"));
    }

    // Survival gate threshold
    private static final double LOW_HP = 0.30;
    private static final double CRIT_HP = 0.15;

    // Infinite loop detection
    private final Map<String, Integer> actionCounts = new HashMap<>();
    private String lastAction = "";
    private int repeatCount = 0;
    private static final int LOOP_THRESHOLD = 5;

    public ArbitrationLayer(GoalFSM fsm, WorldMemory memory) {
        this.fsm = fsm;
        this.memory = memory;
    }

    public GoalFSM getFsm() { return fsm; }

    /** Main decision method */
    public String decide(WorldState state) {
        // 1. Survival gate — danger overrides phase
        boolean danger = state.isDanger();
        double hpFrac = state.hpFraction();

        if (hpFrac < CRIT_HP) {
            // Critical — must flee or heal
            if (state.inCombat) return "flee";
            return "heal";
        }

        if (danger && hpFrac < LOW_HP) {
            // Low HP in danger — escape
            if (state.inCombat) return "flee";
        }

        // 2. FSM phase gate
        String phase = mapFsmToPhase(fsm.getCurrent());
        List<String> allowed = PHASE_ALLOWED.getOrDefault(phase, Collections.emptyList());

        // 3. Filter candidates by world state
        List<String> candidates = new ArrayList<>(allowed);

        // Remove farm if no mob in melee range
        if (!state.hasMobInMeleeRange()) {
            candidates.remove("farm");
        }

        // Remove accept_quest if quest is already active (CRITICAL INVARIANT)
        if (state.quests != null && state.quests.active != null && !state.quests.active.isEmpty()) {
            candidates.remove("accept_quest");
        }

        // Remove return_to_giver if no active quest
        if (state.quests == null || state.quests.active == null || state.quests.active.isEmpty()) {
            candidates.remove("return_to_giver");
            candidates.remove("turn_in");
        }

        // 4. Select best candidate
        String selected = selectBest(candidates, state);

        // 5. Infinite loop detection
        if (selected.equals(lastAction)) {
            repeatCount++;
            if (repeatCount >= LOOP_THRESHOLD) {
                // Force different action
                candidates.remove(selected);
                if (!candidates.isEmpty()) {
                    selected = candidates.get(0);
                }
                repeatCount = 0;
            }
        } else {
            repeatCount = 0;
        }
        lastAction = selected;

        return selected != null ? selected : "noop";
    }

    private String mapFsmToPhase(GoalFSM.QuestState state) {
        switch (state) {
            case QUEST_NONE: return "NO_QUEST";
            case FIND_GIVER: return "FIND_GIVER";
            case ACCEPT: return "ACCEPT";
            case DO_OBJECTIVE: return "DO_OBJECTIVE";
            case VERIFY_PROGRESS: return "DO_OBJECTIVE";
            case RETURN_TO_GIVER: return "RETURN_TO_GIVER";
            case TURN_IN: return "TURN_IN";
            case QUEST_COMPLETE: return "NO_QUEST";
            default: return "NO_QUEST";
        }
    }

    private String selectBest(List<String> candidates, WorldState state) {
        if (candidates.isEmpty()) return "noop";
        // Simple priority: farm > navigate > explore > others
        if (candidates.contains("farm") && state.hasMobInMeleeRange()) return "farm";
        if (candidates.contains("turn_in") && state.quests != null && state.quests.ready != null && !state.quests.ready.isEmpty()) return "turn_in";
        if (candidates.contains("return_to_giver")) return "return_to_giver";
        if (candidates.contains("navigate")) return "navigate";
        return candidates.get(0);
    }
}
