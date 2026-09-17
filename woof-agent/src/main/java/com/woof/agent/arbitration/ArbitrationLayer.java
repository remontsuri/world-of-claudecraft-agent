package com.woof.agent.arbitration;

import com.woof.agent.env.Entity;
import com.woof.agent.env.WorldState;
import com.woof.agent.fsm.GoalFSM;
import com.woof.agent.memory.WorldMemory;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * ArbitrationLayer — решает, какой навык выполнять.
 * Гейты фаз, спасение при опасности, защита от бесконечного цикла.
 *
 * Порядок приоритетов (был сломан: return_to_giver выбирался всегда, пока есть
 * активный квест, то есть агент бегал к NPC вместо выполнения цели):
 *   1. квест готов к сдаче  -> turn_in (NPC рядом) / return_to_giver
 *   2. квеста нет, но NPC с квестом рядом -> accept_quest
 *   3. моб в радиусе атаки  -> farm
 *   4. труп в радиусе       -> loot
 *   5. активный квест       -> navigate (к цели из памяти/снимка)
 *   6. иначе                -> explore
 */
public class ArbitrationLayer {
    private final GoalFSM fsm;
    private final WorldMemory memory;

    private static final Map<String, List<String>> PHASE_ALLOWED = new HashMap<>();
    static {
        PHASE_ALLOWED.put("NO_QUEST", Arrays.asList("accept_quest", "farm", "loot", "explore", "navigate", "gather"));
        PHASE_ALLOWED.put("FIND_GIVER", Arrays.asList("accept_quest", "navigate", "explore"));
        PHASE_ALLOWED.put("ACCEPT", Arrays.asList("accept_quest"));
        PHASE_ALLOWED.put("DO_OBJECTIVE", Arrays.asList("farm", "loot", "navigate", "gather",
                "heal", "sell", "buy", "equip", "cast_frostbolt", "cast_fireball", "explore"));
        PHASE_ALLOWED.put("RETURN_TO_GIVER", Arrays.asList("return_to_giver", "navigate", "flee"));
        PHASE_ALLOWED.put("TURN_IN", Arrays.asList("turn_in", "flee"));
        PHASE_ALLOWED.put("SELL_REPAIR", Arrays.asList("sell", "buy"));
        PHASE_ALLOWED.put("HEAL", Arrays.asList("heal"));
    }

    private static final double LOW_HP = 0.30;
    private static final double CRIT_HP = 0.15;
    private static final int LOOP_THRESHOLD = 6;

    // Навык, который стабильно проваливается, временно исключается из выбора:
    // иначе агент бесконечно повторяет заведомо неуспешный вызов (например
    // accept_quest, когда у NPC больше нет квестов).
    private static final int FAIL_LIMIT = 3;
    private static final int FAIL_COOLDOWN = 60;
    private final Map<String, Integer> failures = new HashMap<>();
    private final Map<String, Integer> cooldown = new HashMap<>();

    private String lastAction = "";
    private int repeatCount = 0;

    public ArbitrationLayer(GoalFSM fsm, WorldMemory memory) {
        this.fsm = fsm;
        this.memory = memory;
    }

    public GoalFSM getFsm() { return fsm; }

    /** Результат исполнения: серия провалов -> временный запрет навыка. */
    public void reportResult(String skill, boolean ok) {
        if (skill == null) return;
        if (ok) {
            failures.remove(skill);
            cooldown.remove(skill);
            return;
        }
        int f = failures.merge(skill, 1, Integer::sum);
        if (f >= FAIL_LIMIT) {
            failures.remove(skill);
            cooldown.put(skill, FAIL_COOLDOWN);
        }
    }

    /** Навыки на перерыве (для журнала). */
    public java.util.Set<String> onCooldown() {
        return new java.util.HashSet<>(cooldown.keySet());
    }

    public String decide(WorldState state) {
        if (state == null || state.player == null) return "noop";

        double hpFrac = state.hpFraction();
        if (hpFrac < CRIT_HP) {
            return state.hasMobInMeleeRange() ? "flee" : "heal";
        }
        if (hpFrac < LOW_HP && state.hasMobInMeleeRange()) {
            return "flee";
        }

        // Тик перерывов
        for (java.util.Iterator<Map.Entry<String, Integer>> it = cooldown.entrySet().iterator(); it.hasNext(); ) {
            Map.Entry<String, Integer> e = it.next();
            int left = e.getValue() - 1;
            if (left <= 0) it.remove(); else e.setValue(left);
        }

        String phase = mapFsmToPhase(fsm.getCurrent());
        List<String> allowed = new ArrayList<>(PHASE_ALLOWED.getOrDefault(phase, Collections.emptyList()));
        for (String blocked : cooldown.keySet()) allowed.remove(blocked);

        // Инвариант: активный квест нельзя взять заново
        if (state.hasActiveQuest() || state.hasReadyQuest()) {
            allowed.remove("accept_quest");
        }
        if (!state.hasActiveQuest() && !state.hasReadyQuest()) {
            allowed.remove("return_to_giver");
            allowed.remove("turn_in");
        }

        String selected = selectBest(allowed, state);

        if (selected.equals(lastAction)) {
            if (++repeatCount >= LOOP_THRESHOLD) {
                List<String> alt = new ArrayList<>(allowed);
                alt.remove(selected);
                if (!alt.isEmpty()) selected = alt.get(0);
                repeatCount = 0;
            }
        } else {
            repeatCount = 0;
        }
        lastAction = selected;
        memory.recordAction(selected);
        return selected;
    }

    private String mapFsmToPhase(GoalFSM.QuestState st) {
        switch (st) {
            case QUEST_NONE:        return "NO_QUEST";
            case FIND_GIVER:        return "FIND_GIVER";
            case ACCEPT:            return "ACCEPT";
            case DO_OBJECTIVE:
            case VERIFY_PROGRESS:   return "DO_OBJECTIVE";
            case RETURN_TO_GIVER:   return "RETURN_TO_GIVER";
            case TURN_IN:           return "TURN_IN";
            case QUEST_COMPLETE:    return "NO_QUEST";
            default:                return "NO_QUEST";
        }
    }

    /** Первый допустимый навык из приоритетного списка. */
    private String selectBest(List<String> allowed, WorldState state) {
        if (allowed.isEmpty()) return "noop";
        boolean giverNear = state.questGiverInRange() != null;
        boolean ready = state.hasReadyQuest();
        boolean active = state.hasActiveQuest();

        List<String> priority = new ArrayList<>();
        if (ready) priority.add(giverNear ? "turn_in" : "return_to_giver");
        if (!ready && !active && giverNear) priority.add("accept_quest");
        if (state.hasMobInMeleeRange()) priority.add("farm");
        if (state.lootInRange() != null) priority.add("loot");
        if (active) priority.add("navigate");
        if (!ready && !active && !giverNear && findGiver(state) != null) priority.add("navigate");
        priority.add("explore");

        for (String p : priority) {
            if (allowed.contains(p)) return p;
        }
        return allowed.get(0);
    }

    /** NPC с canQuest без ограничения радиуса (цель для navigate). */
    private Entity findGiver(WorldState state) {
        if (state.nearby == null) return null;
        return state.nearby.stream()
                .filter(e -> "npc".equals(e.kind) && Boolean.TRUE.equals(e.canQuest))
                .min((a, b) -> Double.compare(
                        a.dist != null ? a.dist : 999.0,
                        b.dist != null ? b.dist : 999.0))
                .orElse(null);
    }
}
