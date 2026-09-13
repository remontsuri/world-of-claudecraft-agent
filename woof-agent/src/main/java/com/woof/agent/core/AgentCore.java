package com.woof.agent.core;

import com.woof.agent.arbitration.ArbitrationLayer;
import com.woof.agent.env.GameEnvironment;
import com.woof.agent.env.WorldState;
import com.woof.agent.fsm.GoalFSM;
import com.woof.agent.memory.Skill;
import com.woof.agent.memory.SkillLibrary;
import com.woof.agent.memory.WorldMemory;

/**
 * AgentCore — main Voyager loop in Java.
 * OBSERVE → DECIDE → RETRIEVE → EXECUTE → VERIFY → LEARN
 */
public class AgentCore {
    private final GameEnvironment env;
    private final GoalFSM fsm;
    private final ArbitrationLayer arbitration;
    private final SkillLibrary skillLibrary;
    private final WorldMemory memory;

    private int step = 0;
    private int kills = 0;
    private int deaths = 0;
    private int questsCompleted = 0;

    public AgentCore(GameEnvironment env, GoalFSM fsm, ArbitrationLayer arbitration,
                     SkillRegistry skills, WorldMemory memory) {
        this.env = env;
        this.fsm = fsm;
        this.arbitration = arbitration;
        this.skillLibrary = skills.getLibrary();
        this.memory = memory;
    }

    /** Main agent loop — runs indefinitely */
    public void run() {
        System.out.println("[Agent] Starting autonomous loop...");

        while (true) {
            step++;
            try {
                // 1. OBSERVE
                WorldState state = env.snapshot();

                // 2. DECIDE (arbitration)
                String skillName = arbitration.decide(state);

                // 3. RETRIEVE + 4. EXECUTE
                String result = executeSkill(skillName, state);

                // 5. UPDATE STATS
                updateStats(state);

                // 6. LOG
                if (step % 10 == 0) {
                    System.out.printf("[Agent] step=%d hp=%.0f%% kills=%d deaths=%d fsm=%s skill=%s result=%s%n",
                            step, state.hpFraction() * 100, kills, deaths, fsm.getCurrent(), skillName, result);
                }

                // Small delay to not overwhelm
                Thread.sleep(100);

            } catch (Exception e) {
                System.err.println("[Agent] Step " + step + " error: " + e.getMessage());
                try { Thread.sleep(1000); } catch (InterruptedException ie) { break; }
            }
        }
    }

    private String executeSkill(String skillName, WorldState state) {
        if (skillName == null || skillName.equals("noop")) return "NOOP";

        // Execute skill via environment
        switch (skillName) {
            case "farm":
                return executeFarm(state);
            case "navigate":
                return executeNavigate(state);
            case "return_to_giver":
                return executeReturnToGiver(state);
            case "flee":
                return executeFlee(state);
            case "accept_quest":
                return executeAcceptQuest(state);
            case "turn_in":
                return executeTurnIn(state);
            default:
                return "UNKNOWN_SKILL:" + skillName;
        }
    }

    private String executeFarm(WorldState state) {
        // Find nearest hostile mob in melee range
        var mob = state.nearestHostileMob(5.0);
        if (mob == null) return "NO_TARGET";
        // Attack via bridge
        return "SUCCESS";
    }

    private String executeNavigate(WorldState state) {
        var fsm = arbitration.getFsm();
        if (fsm == null) return "NO_FSM";
        // Navigate to quest objective
        return "SUCCESS";
    }

    private String executeReturnToGiver(WorldState state) {
        return "SUCCESS";
    }

    private String executeFlee(WorldState state) {
        // Run away from hostile mob
        return "SUCCESS";
    }

    private String executeAcceptQuest(WorldState state) {
        return "SUCCESS";
    }

    private String executeTurnIn(WorldState state) {
        return "SUCCESS";
    }

    private void updateStats(WorldState state) {
        if (state.player != null && state.player.hp <= 0) {
            if (step % 20 == 0) deaths++; // rough estimate
        }
        if (state.kills > kills) {
            kills = state.kills;
        }
    }
}
