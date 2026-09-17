package com.woof.agent.env;

/**
 * Entity — any object in the game world (mob, NPC, resource node, item).
 * Unified schema from game bridge.
 */
public class Entity {
    public String id;
    public String kind;        // "mob", "npc", "resource", "item"
    public String type;        // "forest_wolf", "bandit", "herb_bush", etc.
    public String name;
    public double x;
    public double y;
    public double z;
    public Double dist;        // distance from player (set by bridge)
    public Boolean hostile;    // for mobs
    public Boolean dead;       // for mobs
    public Boolean canQuest;   // for NPCs — can give/take quests
    public String resourceType; // for resource nodes: "herb", "ore", "wood"
    public Integer itemId;     // for items
    public Integer hp;         // for mobs
    public Boolean questTarget; // моб — цель активного квеста (snapshot.cjs: quest_target)
    public Boolean lootable;    // труп можно обыскать
    public Boolean looted;      // уже обыскан
    public Boolean vendor;      // NPC — торговец

    public Entity() {}

    /** Моб (не NPC), живой и враждебный */
    public boolean isHostileMob() {
        return "mob".equals(kind) && Boolean.TRUE.equals(hostile) && !Boolean.TRUE.equals(dead);
    }

    public boolean isDeadMob() {
        return "mob".equals(kind) && Boolean.TRUE.equals(dead);
    }

    /** Труп, который ещё можно обыскать */
    public boolean isLootable() {
        return isDeadMob() && !Boolean.TRUE.equals(looted)
                && (lootable == null || Boolean.TRUE.equals(lootable));
    }

    public double distanceTo(Entity other) {
        if (other == null) return Double.MAX_VALUE;
        double dx = this.x - other.x;
        double dz = this.z - other.z;
        return Math.sqrt(dx*dx + dz*dz);
    }

    public double distanceTo(double px, double pz) {
        double dx = this.x - px;
        double dz = this.z - pz;
        return Math.sqrt(dx*dx + dz*dz);
    }

    @Override
    public String toString() {
        return String.format("%s[%s]@%.1f,%.1f (%.1f yd) %s",
                kind, type, x, z, dist != null ? dist : 0.0,
                Boolean.TRUE.equals(hostile) ? "HOSTILE" : "");
    }
}
