package com.woof.agent.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.woof.agent.env.Entity;
import com.woof.agent.env.GameEnvironment;
import com.woof.agent.env.QuestEntry;
import com.woof.agent.env.WorldState;
import com.woof.agent.fsm.GoalFSM;
import com.woof.agent.memory.WorldMemory;

/**
 * SkillExecutor — единственная точка исполнения навыков.
 *
 * Индексы берутся из SkillIndex (таблица моста), координаты — из снимка
 * (quests[].turnInNpc) с запасным вариантом в памяти, и НИ ОДНОЙ зашитой
 * координаты: прежний код всегда бежал в (2.84, 9.72) «к Apothecary Lin»,
 * что верно только для одного квеста и одной точки мира.
 */
public class SkillExecutor {
    private static final int NAV_MAX_STEPS = 80;
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final GameEnvironment env;
    private final WorldMemory memory;
    private final GoalFSM fsm;

    public SkillExecutor(GameEnvironment env, WorldMemory memory, GoalFSM fsm) {
        this.env = env;
        this.memory = memory;
        this.fsm = fsm;
    }

    public String execute(String skill, WorldState ws) {
        if (skill == null || "noop".equals(skill)) return "NOOP";
        try {
            switch (skill) {
                case "farm":            return farm(ws);
                case "loot":            return loot(ws);
                case "accept_quest":    return acceptQuest(ws);
                case "turn_in":         return turnIn(ws);
                case "return_to_giver": return returnToGiver(ws);
                case "navigate":        return navigate(ws);
                case "flee":            env.rawMove("back"); return "FLEE";
                case "explore":         return explore();
                default:                return plain(skill);
            }
        } catch (Exception e) {
            return "ERROR:" + e.getMessage();
        }
    }

    // ---------------------------------------------------------------- навыки

    /** farm: цель + атака. Подход — задача navigate (в actions.cjs chase убран). */
    private String farm(WorldState ws) {
        Entity mob = nearestQuestMob(ws);
        if (mob == null) mob = ws.nearestHostileMob(WorldState.INTERACT_RANGE);
        if (mob == null) return "NO_TARGET";
        ObjectNode ctx = ctx();
        if (mob.id != null) ctx.put("mobId", mob.id);
        if (mob.type != null) ctx.put("targetMobId", mob.type);
        JsonNode r = env.step(SkillIndex.idx("farm"), ctx);
        return ok(r) ? "FARM:" + (mob.type == null ? mob.id : mob.type) : "FARM_FAILED";
    }

    /** loot: обыскать конкретный труп рядом. */
    private String loot(WorldState ws) {
        Entity corpse = ws.lootInRange();
        if (corpse == null) return "NO_CORPSE";
        ObjectNode ctx = ctx();
        if (corpse.id != null) ctx.put("mobId", corpse.id);
        JsonNode r = env.step(SkillIndex.idx("loot"), ctx);
        return ok(r) ? "LOOT:" + corpse.id : "LOOT_FAILED";
    }

    /** accept_quest: сперва дойти до NPC, ТОЛЬКО ПОТОМ принимать (иначе сервер
     *  отклонит по дальности — INTERACT_RANGE). */
    private String acceptQuest(WorldState ws) {
        Entity giver = ws.questGiverInRange();
        if (giver == null) {
            double[] t = giverCoord(ws);
            if (t == null) return "NO_GIVER";
            boolean arrived = env.navigate(t[0], t[1], NAV_MAX_STEPS);
            return arrived ? "ARRIVED_GIVER" : String.format("NAV_GIVER:%.1f,%.1f", t[0], t[1]);
        }
        ObjectNode ctx = ctx();
        if (giver.id != null) ctx.put("npcId", giver.id);
        JsonNode r = env.step(SkillIndex.idx("accept_quest"), ctx);
        return ok(r) ? "ACCEPT" : "ACCEPT_FAILED";
    }

    /** turn_in: сдать готовый квест (NPC уже в радиусе). */
    private String turnIn(WorldState ws) {
        QuestEntry q = ws.readyQuest();
        if (q == null) return "NO_READY_QUEST";
        ObjectNode ctx = ctx();
        ctx.put("questId", q.id);
        JsonNode r = env.step(SkillIndex.idx("turn_in_quest"), ctx);
        return ok(r) ? "TURN_IN:" + q.id : "TURN_IN_FAILED";
    }

    /** return_to_giver: дойти до точки сдачи, при подходе — сдать. */
    private String returnToGiver(WorldState ws) {
        QuestEntry q = ws.readyQuest();
        double[] t = turnInCoord(q, ws);
        if (t == null) return "NO_GIVER_COORD";
        boolean arrived = env.navigate(t[0], t[1], NAV_MAX_STEPS);
        memory.rememberGiver(q != null ? q.id : "giver", null, t[0], t[1]);
        if (!arrived) return String.format("RETURN_WALK:%.1f,%.1f", t[0], t[1]);
        if (q != null) {
            ObjectNode ctx = ctx();
            ctx.put("questId", q.id);
            JsonNode r = env.step(SkillIndex.idx("turn_in_quest"), ctx);
            return ok(r) ? "RETURN_TURN_IN:" + q.id : "RETURN_ARRIVED";
        }
        return "RETURN_ARRIVED";
    }

    /** navigate: к цели квеста (живой моб, память, точка сдачи). */
    private String navigate(WorldState ws) {
        QuestEntry active = ws.activeQuest();
        double[] target = null;
        String what = "unknown";
        if (active != null) {
            Entity live = nearestQuestMob(ws);
            if (live != null) {
                target = new double[]{live.x, live.z};
                what = "mob:" + active.id;
                memory.saveQuestMobCoord(active.id, live.x, live.z);
            } else {
                target = memory.getQuestMobCoord(active.id);
                what = "mob-mem:" + active.id;
            }
            if (target == null && active.turnInX != null) {
                target = new double[]{active.turnInX, active.turnInZ};
                what = "giver:" + active.id;
            }
        }
        if (target == null) {
            target = turnInCoord(ws.readyQuest(), ws);
            what = "turnin";
        }
        if (target == null) return explore();

        boolean arrived = env.navigate(target[0], target[1], NAV_MAX_STEPS);
        return String.format("%s %s:%.1f,%.1f", arrived ? "ARRIVED" : "WALK", what, target[0], target[1]);
    }

    private String explore() {
        JsonNode r = env.explore(10);
        return r.path("arrived").asBoolean(false) ? "EXPLORE_ARRIVED" : "EXPLORE";
    }

    /** Навык без особой логики: индекс из таблицы, один вызов. */
    private String plain(String skill) {
        if (!SkillIndex.known(skill)) return "UNKNOWN_SKILL:" + skill;
        JsonNode r = env.step(SkillIndex.idx(skill), null);
        return ok(r) ? skill.toUpperCase() : skill.toUpperCase() + "_FAILED";
    }

    // ---------------------------------------------------------------- утилиты

    /** Координаты сдачи: сперва точка из квеста, затем память, затем NPC в снимке. */
    private double[] turnInCoord(QuestEntry q, WorldState ws) {
        if (q != null && q.turnInX != null && q.turnInZ != null) {
            return new double[]{q.turnInX, q.turnInZ};
        }
        if (q != null) {
            double[] m = memory.getGiverLocation(q.id);
            if (m != null) return m;
        }
        return giverCoord(ws);
    }

    private double[] giverCoord(WorldState ws) {
        QuestEntry active = ws.activeQuest();
        if (active != null && active.turnInX != null && active.turnInZ != null) {
            return new double[]{active.turnInX, active.turnInZ};
        }
        Entity giver = ws.questGiverInRange();
        if (giver != null) return new double[]{giver.x, giver.z};
        if (ws.nearby != null) {
            Entity any = ws.nearby.stream()
                    .filter(e -> "npc".equals(e.kind) && Boolean.TRUE.equals(e.canQuest))
                    .min((a, b) -> Double.compare(a.dist != null ? a.dist : 999.0,
                                                  b.dist != null ? b.dist : 999.0))
                    .orElse(null);
            if (any != null) return new double[]{any.x, any.z};
        }
        for (String id : new String[]{"apothecary_lin", "lin", "quest_giver"}) {
            double[] c = ws.npcCoord(id);
            if (c != null) return c;
        }
        return null;
    }

    /** Ближайший ЖИВОЙ моб — цель активного квеста (без ограничения радиуса). */
    private Entity nearestQuestMob(WorldState ws) {
        if (ws.nearby == null) return null;
        return ws.nearby.stream()
                .filter(Entity::isHostileMob)
                .filter(e -> Boolean.TRUE.equals(e.questTarget))
                .min((a, b) -> Double.compare(a.dist != null ? a.dist : 999.0,
                                              b.dist != null ? b.dist : 999.0))
                .orElse(null);
    }

    private ObjectNode ctx() {
        return MAPPER.createObjectNode();
    }

    private boolean ok(JsonNode r) {
        return r != null && r.path("ok").asBoolean(false);
    }
}
