package com.woof.agent.core;

import com.woof.agent.arbitration.ArbitrationLayer;
import com.woof.agent.env.Entity;
import com.woof.agent.env.GameEnvironment;
import com.woof.agent.env.QuestEntry;
import com.woof.agent.env.WorldState;
import com.woof.agent.fsm.GoalFSM;
import com.woof.agent.memory.SkillLibrary;
import com.woof.agent.memory.WorldMemory;

/**
 * AgentCore — главный цикл агента: OBSERVE → DECIDE → EXECUTE → VERIFY → LEARN.
 *
 * Раньше исполнитель навыков здесь был заглушкой (`return "SUCCESS"` без
 * обращения к игре) — цикл «работал» без игры. Теперь исполнение одно на всех:
 * SkillExecutor, тот же, что использует VoyagerAgent.
 */
public class AgentCore {
    private final GameEnvironment env;
    private final GoalFSM fsm;
    private final ArbitrationLayer arbitration;
    private final SkillLibrary skillLibrary;
    private final WorldMemory memory;
    private final SkillExecutor executor;

    private int step = 0;
    private int kills = 0;
    private int deaths = 0;
    private int completedAtStart = 0;
    private int lastQuestsDone = 0;
    private int firstCompletionStep = -1;
    private int pollMs = 50;
    private boolean verbose = true;

    public AgentCore(GameEnvironment env, GoalFSM fsm, ArbitrationLayer arbitration,
                     SkillRegistry skills, WorldMemory memory) {
        this.env = env;
        this.fsm = fsm;
        this.arbitration = arbitration;
        this.skillLibrary = skills.getLibrary();
        this.memory = memory;
        this.executor = new SkillExecutor(env, memory, fsm);
    }

    public void setPollMs(int pollMs) { this.pollMs = pollMs; }
    public void setVerbose(boolean verbose) { this.verbose = verbose; }

    public int getSteps() { return step; }
    public int getKills() { return kills; }
    public int getDeaths() { return deaths; }
    public int getFirstCompletionStep() { return firstCompletionStep; }

    /** Главный цикл; maxSteps <= 0 — до остановки внешним сигналом. */
    public void run(int maxSteps) {
        WorldState ws = env.snapshot();
        completedAtStart = ws.questsDone;
        lastQuestsDone = completedAtStart;
        info("loop start: quests_done=" + completedAtStart
                + " skills=" + skillLibrary.size());

        while (maxSteps <= 0 || step < maxSteps) {
            step++;
            try {
                ws = env.snapshot();                       // 1. OBSERVE

                if (ws.player != null && ws.player.dead) {
                    info("dead -> respawn");
                    env.respawn();
                    sleep(500);
                    continue;
                }

                rememberQuestTargets(ws);                  // LEARN: где живёт цель квеста
                fsm.syncFrom(ws);                          // фаза из наблюдения, не вручную

                String skill = arbitration.decide(ws);     // 2. DECIDE
                String result = executor.execute(skill, ws); // 3. EXECUTE
                arbitration.reportResult(skill, isOk(skill, result));
                verify(ws);                                // 4. VERIFY

                if (verbose && step % 10 == 0) {
                    info(String.format("step=%d phase=%s skill=%s result=%s hp=%.0f%% lvl=%d "
                                    + "kills=%d deaths=%d quests=%d nearby=%d%s",
                            step, fsm.getCurrent(), skill, result, ws.hpFraction() * 100,
                            ws.level, kills, deaths, ws.questsDone,
                            ws.nearby != null ? ws.nearby.size() : 0,
                            arbitration.onCooldown().isEmpty() ? "" : " cooldown=" + arbitration.onCooldown()));
                }
                sleep(pollMs);
            } catch (Exception e) {
                System.err.println("[Agent] step " + step + ": " + e.getMessage());
                sleep(1000);
            }
        }
        summary();
    }

    /** Запомнить координаты ближайшего ЖИВОГО моба — цели активного квеста.
     *  Только живого: координаты убитого моба уводили агента к трупу вместо
     *  следующей цели (проверено на полигоне). */
    private void rememberQuestTargets(WorldState ws) {
        QuestEntry q = ws.activeQuest();
        if (q == null || ws.nearby == null) return;
        Entity best = null;
        for (Entity e : ws.nearby) {
            if (!e.isHostileMob()) continue;
            boolean wanted = Boolean.TRUE.equals(e.questTarget)
                    || (q.targetMobId != null && q.targetMobId.equals(e.type));
            if (!wanted) continue;
            if (best == null || (e.dist != null && (best.dist == null || e.dist < best.dist))) best = e;
        }
        if (best != null) memory.saveQuestMobCoord(q.id, best.x, best.z);
    }

    /** Успех навыка: не провал, не ошибка и не «нет цели/цели нет» */
    private boolean isOk(String skill, String result) {
        if (result == null) return false;
        String r = result.toUpperCase();
        return !r.endsWith("_FAILED") && !r.startsWith("ERROR")
                && !r.startsWith("NO_") && !r.equals("UNKNOWN_SKILL");
    }

    private void verify(WorldState ws) {
        if (ws.kills > kills) {
            if (verbose) info("kill total=" + ws.kills);
            kills = ws.kills;
        }
        if (ws.deaths > deaths) {
            info("death total=" + ws.deaths);
            deaths = ws.deaths;
        }
        lastQuestsDone = ws.questsDone;
        if (firstCompletionStep < 0 && ws.questsDone > completedAtStart) {
            firstCompletionStep = step;
            info("QUEST TURNED IN at step " + step + " (total " + ws.questsDone + ")");
        }
    }

    private void summary() {
        int done = Math.max(fsm.getCompletions(), Math.max(0, lastQuestsDone - completedAtStart));
        info(String.format("SUMMARY steps=%d kills=%d deaths=%d quests_done=%d%s",
                step, kills, deaths, done,
                firstCompletionStep > 0 ? " first_turn_in_step=" + firstCompletionStep : ""));
    }

    private void info(String msg) {
        if (verbose) System.out.println("[Agent] " + msg);
    }

    private void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }
}
