package com.woof.agent.env;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;

/**
 * Разбор ответа моста ({ok, info}) в WorldState.
 *
 * Один маппинг на всех потребителей: мост отдаёт ПЛОСКИЙ снимок (browser_bridge.cjs:
 * "info — это всегда плоское наблюдение, без вложенности"), и любое расхождение в
 * разборе между агентами — источник тихих ошибок. Поля, которых нет в ответе,
 * НЕ перетираются нулём: состояние остаётся прежним.
 */
public final class SnapshotMapper {

    private SnapshotMapper() {}

    /** @return true, если info был объектом и состояние обновлено */
    public static boolean apply(WorldState ws, JsonNode info) {
        if (ws == null || info == null || !info.isObject()) return false;

        JsonNode player = info.path("player");
        if (ws.player == null) ws.player = new PlayerState();
        if (player.isObject()) {
            if (player.hasNonNull("hp")) ws.player.hp = player.get("hp").asInt();
            if (player.hasNonNull("maxHp")) ws.player.maxHp = player.get("maxHp").asInt();
            if (player.hasNonNull("x")) ws.player.x = player.get("x").asDouble();
            if (player.hasNonNull("z")) ws.player.z = player.get("z").asDouble();
            if (player.hasNonNull("facing")) ws.player.facing = player.get("facing").asDouble();
            if (player.hasNonNull("level")) ws.player.level = player.get("level").asInt();
            if (player.hasNonNull("xp")) ws.player.xp = player.get("xp").asInt();
            if (player.hasNonNull("dead")) ws.player.dead = player.get("dead").asBoolean();
            if (player.hasNonNull("in_combat")) ws.player.inCombat = player.get("in_combat").asBoolean();
            if (player.hasNonNull("class")) ws.player.playerClass = player.get("class").asText();
        }
        if (ws.player.maxHp <= 0) ws.player.maxHp = 138;
        if (!player.hasNonNull("dead")) ws.player.dead = ws.player.hp <= 0;

        JsonNode pos = info.path("player_pos");
        if (pos.isArray() && pos.size() >= 2) {
            ws.playerPos = new double[]{pos.get(0).asDouble(), pos.get(1).asDouble()};
        }

        if (info.hasNonNull("kills")) ws.kills = info.get("kills").asInt();
        if (info.hasNonNull("deaths")) ws.deaths = info.get("deaths").asInt();
        if (info.hasNonNull("level")) ws.level = info.get("level").asInt();
        if (info.hasNonNull("xp")) ws.xp = info.get("xp").asInt();
        if (info.hasNonNull("copper")) ws.copper = info.get("copper").asInt();
        if (info.hasNonNull("in_combat")) ws.inCombat = info.get("in_combat").asBoolean();
        if (info.hasNonNull("quests_done")) ws.questsDone = info.get("quests_done").asInt();
        if (info.hasNonNull("mana")) ws.mana = info.get("mana").asInt();
        if (info.hasNonNull("maxMana")) ws.maxMana = info.get("maxMana").asInt();
        if (info.hasNonNull("player_class")) ws.playerClass = info.get("player_class").asText();

        ws.nearby = mapEntities(info.path("nearby"));

        JsonNode npc = info.path("npc_positions");
        if (npc.isObject()) {
            ws.npcPositions = new HashMap<>();
            npc.fields().forEachRemaining(e -> {
                JsonNode v = e.getValue();
                if (v.isArray() && v.size() >= 2) {
                    ws.npcPositions.put(e.getKey(), new double[]{v.get(0).asDouble(), v.get(1).asDouble()});
                }
            });
        }

        JsonNode blocked = info.path("quest_cadence_blocked");
        if (blocked.isArray()) {
            List<String> ids = new ArrayList<>();
            for (JsonNode b : blocked) ids.add(b.asText());
            ws.questCadenceBlocked = ids;
        }

        JsonNode quests = info.path("quests");
        if (quests.isObject()) {
            QuestInfo qi = new QuestInfo();
            qi.active = mapQuests(quests.path("active"));
            qi.ready = mapQuests(quests.path("ready"));
            qi.done = mapQuests(quests.path("done"));
            ws.quests = qi;
        }

        ws.hasMob = ws.hasMobInMeleeRange();
        ws.hasGiver = ws.hasQuestGiver();
        ws.danger = ws.isDanger();
        return true;
    }

    private static List<Entity> mapEntities(JsonNode arr) {
        List<Entity> out = new ArrayList<>();
        if (arr == null || !arr.isArray()) return out;
        for (JsonNode e : arr) {
            Entity ent = new Entity();
            ent.id = e.path("id").isMissingNode() ? null : e.path("id").asText();
            ent.kind = e.path("kind").asText("");
            ent.type = e.path("templateId").asText(e.path("type").asText(""));
            ent.name = e.path("name").asText("");
            ent.x = e.path("x").asDouble(0);
            ent.z = e.path("z").asDouble(0);
            if (e.hasNonNull("dist")) ent.dist = e.get("dist").asDouble();
            if (e.hasNonNull("hostile")) ent.hostile = e.get("hostile").asBoolean();
            if (e.hasNonNull("dead")) ent.dead = e.get("dead").asBoolean();
            if (e.hasNonNull("canQuest")) ent.canQuest = e.get("canQuest").asBoolean();
            if (e.hasNonNull("hp")) ent.hp = e.get("hp").asInt();
            if (e.hasNonNull("quest_target")) ent.questTarget = e.get("quest_target").asBoolean();
            if (e.hasNonNull("lootable")) ent.lootable = e.get("lootable").asBoolean();
            if (e.hasNonNull("looted")) ent.looted = e.get("looted").asBoolean();
            if (e.hasNonNull("vendor")) ent.vendor = e.get("vendor").asBoolean();
            out.add(ent);
        }
        return out;
    }

    private static List<QuestEntry> mapQuests(JsonNode arr) {
        List<QuestEntry> out = new ArrayList<>();
        if (arr == null || !arr.isArray()) return out;
        for (JsonNode q : arr) {
            QuestEntry entry = new QuestEntry();
            entry.id = q.path("id").asText("");
            entry.name = q.path("name").asText("");
            entry.state = q.path("state").asText("");
            entry.giverId = q.path("giverId").asText("");
            entry.giverName = q.path("giverName").asText("");
            entry.targetMobId = q.path("targetMobId").asText("");
            if (q.hasNonNull("progress")) entry.progress = q.get("progress").asInt();
            if (q.hasNonNull("required")) entry.required = q.get("required").asInt();
            if (q.hasNonNull("killCount")) entry.killCount = q.get("killCount").asInt();
            JsonNode turnIn = q.path("turnInNpc");
            if (turnIn.isObject()) {
                if (turnIn.hasNonNull("x")) entry.turnInX = turnIn.get("x").asDouble();
                if (turnIn.hasNonNull("z")) entry.turnInZ = turnIn.get("z").asDouble();
                if (turnIn.hasNonNull("name")) entry.turnInNpcName = turnIn.get("name").asText();
            }
            out.add(entry);
        }
        return out;
    }
}
