package com.woof.agent.env;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/**
 * WorldState — canonical source of truth for agent decisions.
 * Single semantic source (no situation where game→bridge→info and game→observation differ).
 */
public class WorldState {
    // Player
    @JsonProperty("player") public PlayerState player;
    @JsonProperty("player_pos") public double[] playerPos;
    @JsonProperty("facing") public double facing;

    // World
    @JsonProperty("nearby") public List<Entity> nearby;
    @JsonProperty("npc_positions") public Map<String, double[]> npcPositions;

    // Quests
    @JsonProperty("quests") public QuestInfo quests;
    @JsonProperty("quests_done") public int questsDone;
    @JsonProperty("quest_cadence_blocked") public List<String> questCadenceBlocked;

    // Combat
    @JsonProperty("kills") public int kills;
    @JsonProperty("deaths") public int deaths;
    @JsonProperty("in_combat") public boolean inCombat;
    @JsonProperty("target") public Entity target;

    // Misc
    @JsonProperty("copper") public int copper;
    @JsonProperty("level") public int level;
    @JsonProperty("xp") public int xp;
    @JsonProperty("mana") public int mana;
    @JsonProperty("maxMana") public int maxMana;

    // Inventory
    @JsonProperty("inventory") public java.util.List<ItemStack> inventory;
    @JsonProperty("bagCapacity") public int bagCapacity;
    @JsonProperty("bags") public int bags;

    // Vendor
    @JsonProperty("vendor") public VendorState vendor;
    @JsonProperty("vendor_offers") public VendorState vendorOffers;

    // Abilities
    @JsonProperty("abilities") public Map<String, Object> abilities;
    @JsonProperty("recipes_known") public List<String> recipesKnown;
    @JsonProperty("stations") public List<String> stations;
    @JsonProperty("player_class") public String playerClass;

    /** Радиус взаимодействия в игре (gathering.ts INTERACT_RANGE) */
    public static final double INTERACT_RANGE = 5.0;

    // Computed flags
    @JsonProperty("has_mob") public boolean hasMob;
    @JsonProperty("has_giver") public boolean hasGiver;
    @JsonProperty("danger") public boolean danger;

    public WorldState() {}

    // === Derived properties ===

    /** Fractional HP (0.0 = dead, 1.0 = full) */
    public double hpFraction() {
        if (player == null || player.maxHp <= 0) return 0.0;
        return (double) player.hp / player.maxHp;
    }

    /** Is the player in danger? (dead OR low HP OR in combat) */
    public boolean isDanger() {
        return (player != null && player.hp <= 0) || hpFraction() < 0.3 || inCombat;
    }

    /** Is there a hostile mob within melee range (≤5.0 yards)? */
    public boolean hasMobInMeleeRange() {
        if (nearby == null) return false;
        double range = 5.0; // ATTACK_RANGE = 5.0 from official source
        return nearby.stream()
                .anyMatch(e -> "mob".equals(e.kind) && Boolean.TRUE.equals(e.hostile)
                        && !Boolean.TRUE.equals(e.dead)
                        && e.dist != null && e.dist <= range);
    }

    /** Is there a quest giver nearby? */
    public boolean hasQuestGiver() {
        if (nearby == null) return false;
        return nearby.stream()
                .anyMatch(e -> "npc".equals(e.kind) && (e.canQuest != null && e.canQuest));
    }

    /** Есть ли активный (взят и не сдан) квест */
    public boolean hasActiveQuest() {
        return quests != null && quests.active != null && !quests.active.isEmpty();
    }

    /** Есть ли квест, готовый к сдаче */
    public boolean hasReadyQuest() {
        return quests != null && quests.ready != null && !quests.ready.isEmpty();
    }

    /** Ближайший готовый к сдаче квест */
    public QuestEntry readyQuest() {
        return hasReadyQuest() ? quests.ready.get(0) : null;
    }

    /** Первый активный квест */
    public QuestEntry activeQuest() {
        return hasActiveQuest() ? quests.active.get(0) : null;
    }

    /** NPC, который может дать/принять квест, в радиусе взаимодействия */
    public Entity questGiverInRange() {
        if (nearby == null) return null;
        return nearby.stream()
                .filter(e -> "npc".equals(e.kind) && Boolean.TRUE.equals(e.canQuest))
                .filter(e -> e.dist != null && e.dist <= INTERACT_RANGE)
                .min((a, b) -> Double.compare(a.dist, b.dist))
                .orElse(null);
    }

    /** Ближайший ЕЩЁ НЕ ОБЫСКАННЫЙ труп (для loot).
     *  Фильтр по isLootable, а не isDeadMob: иначе агент бесконечно «обыскивает»
     *  уже обысканный труп — проверено на полигоне, зацикливался насмерть. */
    public Entity lootInRange() {
        if (nearby == null) return null;
        return nearby.stream()
                .filter(Entity::isLootable)
                .filter(e -> e.dist != null && e.dist <= INTERACT_RANGE)
                .min((a, b) -> Double.compare(a.dist, b.dist))
                .orElse(null);
    }

    /** Квест в кулдауне (повторяемые work-order): брать нельзя */
    public boolean isCadenceBlocked(String questId) {
        return questCadenceBlocked != null && questId != null && questCadenceBlocked.contains(questId);
    }

    /** Координаты NPC по имени/id из снимка */
    public double[] npcCoord(String npcId) {
        if (npcPositions == null || npcId == null) return null;
        return npcPositions.get(npcId);
    }

    /** Find nearest hostile mob within range */
    public Entity nearestHostileMob(double maxDist) {
        if (nearby == null) return null;
        return nearby.stream()
                .filter(e -> "mob".equals(e.kind) && Boolean.TRUE.equals(e.hostile)
                        && !Boolean.TRUE.equals(e.dead)
                        && e.dist != null && e.dist <= maxDist)
                .min((a, b) -> Double.compare(a.dist != null ? a.dist : 999.0,
                                              b.dist != null ? b.dist : 999.0))
                .orElse(null);
    }
}
