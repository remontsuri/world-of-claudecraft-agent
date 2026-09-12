package com.woof.agent;

import com.woof.agent.bridge.BridgeServer;
import com.woof.agent.core.AgentCore;
import com.woof.agent.core.SkillRegistry;
import com.woof.agent.env.GameEnvironment;
import com.woof.agent.fsm.GoalFSM;
import com.woof.agent.memory.SkillLibrary;
import com.woof.agent.memory.WorldMemory;
import com.woof.agent.arbitration.ArbitrationLayer;

/**
 * Bootstrap — full agent startup.
 * Loads all skills, starts bridge, runs Voyager loop.
 */
public class Bootstrap {
    public static void main(String[] args) throws Exception {
        System.out.println("[WoOF] Starting WoOF Agent v1.0.0");
        System.out.println("[WoOF] Stack: Java 17 + Voyager Architecture + WoC-MCP");
        System.out.println("[WoOF] ");

        // Initialize memory and skill library
        WorldMemory memory = new WorldMemory();
        SkillLibrary skillLibrary = new SkillLibrary();
        SkillRegistry skillRegistry = new SkillRegistry(skillLibrary);
        System.out.println("[WoOF] Loaded " + skillLibrary.size() + " skills");

        // Initialize game environment (connects to bridge)
        GameEnvironment env = new GameEnvironment();
        System.out.println("[WoOF] Game environment initialized");

        // Initialize FSM and arbitration
        GoalFSM fsm = new GoalFSM();
        ArbitrationLayer arbitration = new ArbitrationLayer(fsm, memory);

        // Create agent core
        AgentCore agent = new AgentCore(env, fsm, arbitration, skillRegistry, memory);

        // Start bridge server
        BridgeServer bridge = new BridgeServer(8791, env);
        bridge.connect();
        System.out.println("[WoOF] Bridge connected on :8791");

        // Run agent loop
        System.out.println("[WoOF] ====================================");
        System.out.println("[WoOF] Starting autonomous game loop...");
        System.out.println("[WoOF] ====================================");
        agent.run();
    }
}
