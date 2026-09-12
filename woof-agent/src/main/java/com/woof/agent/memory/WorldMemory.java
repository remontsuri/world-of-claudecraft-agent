package com.woof.agent.memory;

import com.woof.agent.env.Entity;
import java.util.*;

/**
 * WorldMemory — persistent memory of quest givers, locations, learned facts.
 */
public class WorldMemory {
    public Map<String, double[]> questGivers = new HashMap<>();
    public Map<String, Entity> knownEntities = new HashMap<>();
    public Set<String> visitedLocations = new HashSet<>();
    public List<String> recentActions = new ArrayList<>();
    private Map<String, double[]> questMobCoords = new HashMap<>();

    public void rememberGiver(String questId, String npcId, double x, double z) {
        questGivers.put(questId, new double[]{x, z});
        questGivers.put(npcId, new double[]{x, z});
    }

    public double[] getGiverLocation(String questId) {
        return questGivers.get(questId);
    }

    public void saveQuestMobCoord(String questId, double x, double z) {
        questMobCoords.put(questId, new double[]{x, z});
    }

    public double[] getQuestMobCoord(String questId) {
        return questMobCoords.get(questId);
    }

    public void recordAction(String action) {
        recentActions.add(action);
        if (recentActions.size() > 100) {
            recentActions.remove(0);
        }
    }
}
