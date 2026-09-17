package com.woof.agent;

import com.woof.agent.arbitration.ArbitrationLayer;
import com.woof.agent.core.AgentCore;
import com.woof.agent.core.SkillRegistry;
import com.woof.agent.env.GameEnvironment;
import com.woof.agent.env.WorldState;
import com.woof.agent.fsm.GoalFSM;
import com.woof.agent.memory.SkillLibrary;
import com.woof.agent.memory.WorldMemory;

/**
 * VoyagerAgent — точка входа автономного агента.
 *
 * Запуск:  java -cp "build/classes:libs/*" com.woof.agent.VoyagerAgent [--steps N] [--bridge URL]
 * Мост по умолчанию: http://127.0.0.1:8791/ (browser_bridge.cjs или Java-мост с тем же контрактом).
 *
 * Сам цикл живёт в AgentCore — здесь только сборка графа и разбор аргументов,
 * чтобы не было второй, расходящейся реализации агента.
 */
public class VoyagerAgent {
    private final GameEnvironment env;
    private final GoalFSM fsm = new GoalFSM();
    private final WorldMemory memory = new WorldMemory();
    private final ArbitrationLayer arbitration;
    private final AgentCore agent;

    public VoyagerAgent(String bridgeUrl) {
        this.env = new GameEnvironment(bridgeUrl);
        this.arbitration = new ArbitrationLayer(fsm, memory);
        SkillLibrary library = new SkillLibrary();
        SkillRegistry registry = new SkillRegistry(library);
        this.agent = new AgentCore(env, fsm, arbitration, registry, memory);
    }

    public AgentCore core() { return agent; }
    public GameEnvironment env() { return env; }
    public GoalFSM fsm() { return fsm; }

    public static void main(String[] args) throws Exception {
        String bridge = "http://127.0.0.1:8791/";
        int steps = 0;              // 0 = без ограничения
        int pollMs = 50;
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--steps":   steps = Integer.parseInt(args[++i]); break;
                case "--bridge":  bridge = args[++i]; break;
                case "--poll-ms": pollMs = Integer.parseInt(args[++i]); break;
                case "--quiet":   break;
                default:
                    if (!args[i].startsWith("--")) bridge = args[i];
            }
        }

        System.out.println("[WoOF] Voyager Agent: bridge=" + bridge
                + (steps > 0 ? " max_steps=" + steps : " unlimited"));

        VoyagerAgent a = new VoyagerAgent(bridge);
        a.agent.setPollMs(pollMs);

        if (!a.env.health()) {
            System.err.println("[WoOF] bridge unreachable at " + bridge
                    + " - start browser_bridge.cjs (node) or the Java bridge, then retry.");
            System.exit(2);
        }
        WorldState ws = a.env.snapshot();
        if (ws.player == null || ws.player.maxHp <= 0) {
            System.err.println("[WoOF] bridge answers but snapshot is empty: is the game page attached?");
            System.exit(3);
        }
        System.out.printf("[WoOF] start: hp=%d/%d pos=(%.1f, %.1f) phase=%s%n",
                ws.player.hp, ws.player.maxHp, ws.player.x, ws.player.z, a.fsm.getCurrent());
        a.agent.run(steps);
    }
}
