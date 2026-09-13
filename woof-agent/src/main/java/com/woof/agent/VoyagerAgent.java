package com.woof.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class VoyagerAgent {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private final String bridgeUrl;
    private int step = 0;
    private int kills = 0;
    private int deaths = 0;
    private com.woof.agent.env.WorldState worldState;
    private com.woof.agent.fsm.GoalFSM fsm;
    private com.woof.agent.arbitration.ArbitrationLayer arbitration;
    private com.woof.agent.memory.WorldMemory memory;

    public VoyagerAgent(String bridgeUrl) {
        this.bridgeUrl = bridgeUrl.endsWith("/") ? bridgeUrl : bridgeUrl + "/";
        this.memory = new com.woof.agent.memory.WorldMemory();
        this.worldState = new com.woof.agent.env.WorldState();
        this.fsm = new com.woof.agent.fsm.GoalFSM();
        this.arbitration = new com.woof.agent.arbitration.ArbitrationLayer(fsm, memory);
    }

    public static void main(String[] args) throws Exception {
        String url = args.length > 0 ? args[0] : "http://127.0.0.1:8791/";
        new VoyagerAgent(url).run();
    }

    public void run() throws Exception {
        System.out.println("[WoOF] Voyager Agent starting... Bridge: " + bridgeUrl);
        JsonNode health = bridgePost("{\"action\":\"health\"}");
        System.out.println("[WoOF] Bridge health: " + health);

        while (step < 10000) {
            step++;
            try {
                observe();

                if (worldState.player != null && worldState.player.hp <= 0) {
                    System.out.println("[WoOF] DEAD! Respawning...");
                    bridgePost("{\"action\":\"respawn\"}");
                    sleep(500);
                    continue;
                }

                String skill = arbitration.decide(worldState);
                if (skill == null || skill.equals("noop")) {
                    sleep(200);
                    continue;
                }

                String result = executeSkill(skill);

                if (step % 5 == 0) verify();

                if (step % 10 == 0) {
                    System.out.printf("[WoOF] step=%d skill=%s result=%s hp=%.0f%% kills=%d deaths=%d quest=%s fsm=%s nearby=%d%n",
                            step, skill, result, worldState.hpFraction() * 100, kills, deaths,
                            getActiveQuestName(), fsm.getCurrent(),
                            worldState.nearby != null ? worldState.nearby.size() : 0);
                }
                sleep(50);
            } catch (Exception e) {
                System.err.println("[WoOF] Step " + step + " error: " + e.getMessage());
                sleep(1000);
            }
        }
    }

    private void observe() throws Exception {
        JsonNode resp = bridgePost("{\"action\":\"snapshot\"}");
        JsonNode info = resp.path("info");
        if (info.isObject()) updateState(info);
    }

    private void updateState(JsonNode info) {
        JsonNode player = info.path("player");
        if (worldState.player == null) worldState.player = new com.woof.agent.env.PlayerState();
        worldState.player.hp = player.path("hp").asInt(0);
        worldState.player.maxHp = player.path("maxHp").asInt(138);
        worldState.player.x = player.path("x").asDouble(0);
        worldState.player.z = player.path("z").asDouble(0);
        worldState.player.facing = player.path("facing").asDouble(0);

        JsonNode pos = info.path("player_pos");
        if (pos.isArray() && pos.size() >= 2) {
            worldState.playerPos = new double[]{pos.get(0).asDouble(), pos.get(1).asDouble()};
        }

        worldState.kills = info.path("kills").asInt(worldState.kills);
        worldState.deaths = info.path("deaths").asInt(worldState.deaths);
        worldState.level = info.path("level").asInt(worldState.level);
        worldState.inCombat = info.path("in_combat").asBoolean(false);

        JsonNode nearby = info.path("nearby");
        worldState.nearby = new ArrayList<>();
        if (nearby.isArray()) {
            for (JsonNode e : nearby) {
                com.woof.agent.env.Entity ent = new com.woof.agent.env.Entity();
                ent.id = String.valueOf(e.path("id").asInt());
                ent.kind = e.path("kind").asText();
                ent.type = e.path("templateId").asText();
                ent.name = e.path("name").asText();
                ent.x = e.path("x").asDouble(0);
                ent.z = e.path("z").asDouble(0);
                ent.dist = e.path("dist").asDouble(0);
                ent.hostile = e.path("hostile").asBoolean(false);
                ent.dead = e.path("dead").asBoolean(false);
                worldState.nearby.add(ent);

                if ("mob".equals(ent.kind) && ent.hostile && !ent.dead) {
                    com.woof.agent.env.QuestEntry q = getActiveQuest();
                    if (q != null && ent.type.equals(q.targetMobId)) {
                        memory.saveQuestMobCoord(q.id, ent.x, ent.z);
                    }
                }
            }
        }

        JsonNode quests = info.path("quests");
        worldState.quests = new com.woof.agent.env.QuestInfo();
        worldState.quests.active = new ArrayList<>();
        JsonNode active = quests.path("active");
        if (active.isArray()) {
            for (JsonNode q : active) {
                com.woof.agent.env.QuestEntry entry = new com.woof.agent.env.QuestEntry();
                entry.id = q.path("id").asText();
                entry.state = q.path("state").asText();
                entry.targetMobId = q.path("targetMobId").asText();
                worldState.quests.active.add(entry);
            }
        }
        worldState.hasMob = worldState.hasMobInMeleeRange();
        worldState.danger = worldState.isDanger();
    }

    private String executeSkill(String skill) throws Exception {
        switch (skill) {
            case "farm": {
                // step(0, {targetMobId: ...}) — attack nearest hostile
                com.woof.agent.env.QuestEntry q = getActiveQuest();
                if (q != null && q.targetMobId != null) {
                    bridgePost("{\"action\":\"step\",\"skill\":0,\"targetMobId\":\"" + q.targetMobId + "\"}");
                } else {
                    bridgePost("{\"action\":\"step\",\"skill\":0}");
                }
                return "FARM";
            }
            case "loot":
                bridgePost("{\"action\":\"step\",\"skill\":1}");
                return "LOOT";
            case "accept_quest":
                // Navigate to quest giver first (Apothecary Lin for q_spiders)
                bridgePost("{\"action\":\"navigate\",\"x\":2.84,\"z\":9.72}");
                bridgePost("{\"action\":\"step\",\"skill\":2}");
                fsm.transition(com.woof.agent.fsm.GoalFSM.QuestState.DO_OBJECTIVE);
                return "ACCEPT";
            case "turn_in":
                bridgePost("{\"action\":\"step\",\"skill\":3}");
                fsm.transition(com.woof.agent.fsm.GoalFSM.QuestState.QUEST_NONE);
                return "TURN_IN";
            case "sell":
                bridgePost("{\"action\":\"step\",\"skill\":4}");
                return "SELL";
            case "buy":
                bridgePost("{\"action\":\"step\",\"skill\":5}");
                return "BUY";
            case "gather":
                bridgePost("{\"action\":\"step\",\"skill\":6}");
                return "GATHER";
            case "craft":
                bridgePost("{\"action\":\"step\",\"skill\":7}");
                return "CRAFT";
            case "heal":
                bridgePost("{\"action\":\"step\",\"skill\":8}");
                return "HEAL";
            case "navigate": {
                // Navigate to quest mob coordinates
                com.woof.agent.env.QuestEntry quest = getActiveQuest();
                if (quest == null) return "NO_QUEST";
                double[] coord = memory.getQuestMobCoord(quest.id);
                if (coord != null) {
                    bridgePost("{\"action\":\"navigate\",\"x\":" + coord[0] + ",\"z\":" + coord[1] + "}");
                    return "NAVIGATE:" + coord[0] + "," + coord[1];
                } else {
                    bridgePost("{\"action\":\"explore\",\"steps\":10}");
                    return "EXPLORE_FIND";
                }
            }
            case "return_to_giver":
                bridgePost("{\"action\":\"navigate\",\"x\":2.84,\"z\":9.72}");
                return "RETURN";
            case "flee":
                bridgePost("{\"action\":\"raw_move\",\"direction\":\"back\"}");
                return "FLEE";
            case "explore":
                bridgePost("{\"action\":\"explore\",\"steps\":10}");
                return "EXPLORE";
            default:
                return "UNKNOWN";
        }
    }

    private void verify() {
        if (worldState.kills > kills) {
            kills = worldState.kills;
            System.out.println("[WoOF] KILL! Total kills: " + kills);
        }
        if (worldState.deaths > deaths) {
            deaths = worldState.deaths;
            System.out.println("[WoOF] DEATH! Total deaths: " + deaths);
        }
    }

    private com.woof.agent.env.QuestEntry getActiveQuest() {
        if (worldState.quests != null && worldState.quests.active != null && !worldState.quests.active.isEmpty())
            return worldState.quests.active.get(0);
        return null;
    }

    private String getActiveQuestName() {
        com.woof.agent.env.QuestEntry q = getActiveQuest();
        return q != null ? q.id : "none";
    }

    private JsonNode bridgePost(String jsonBody) throws Exception {
        URL url = new URL(bridgeUrl);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setDoOutput(true);
        conn.setConnectTimeout(5000);
        conn.setReadTimeout(10000);
        try (OutputStream os = conn.getOutputStream()) {
            os.write(jsonBody.getBytes(StandardCharsets.UTF_8));
        }
        int code = conn.getResponseCode();
        InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        BufferedReader reader = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) sb.append(line);
        return MAPPER.readTree(sb.toString());
    }

    private void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }
}
