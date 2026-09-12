package com.woof.agent.env;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.concurrent.atomic.AtomicReference;

/**
 * GameEnvironment — connection to the game via bridge.
 * Communicates with Node.js bridge on port 8791.
 */
public class GameEnvironment {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String BRIDGE_URL = "http://127.0.0.1:8791/";

    // Cached last state
    private final AtomicReference<WorldState> lastState = new AtomicReference<>(new WorldState());

    public WorldState getLastState() {
        return lastState.get();
    }

    /** Fetch fresh snapshot from bridge */
    public WorldState snapshot() {
        try {
            // In production: HTTP GET to bridge /snapshot
            // For now: return cached state
            return lastState.get();
        } catch (Exception e) {
            System.err.println("[GameEnv] Snapshot failed: " + e.getMessage());
            return lastState.get();
        }
    }

    /** Execute action via bridge */
    public JsonNode step(int actionId, java.util.Map<String, Object> ctx) {
        try {
            // In production: HTTP POST to bridge /action
            return MAPPER.createObjectNode();
        } catch (Exception e) {
            System.err.println("[GameEnv] Step failed: " + e.getMessage());
            return MAPPER.createObjectNode();
        }
    }

    public void close() {}

    /** Handle CDP message from bridge */
    public void onCdpMessage(String message) {
        try {
            JsonNode node = MAPPER.readTree(message);
            if (node.has("result") && node.get("result").has("result")) {
                JsonNode val = node.get("result").get("result").get("value");
                if (val != null && val.isObject()) {
                    WorldState ws = MAPPER.treeToValue(val, WorldState.class);
                    lastState.set(ws);
                }
            }
        } catch (Exception e) {
            // ignore malformed
        }
    }
}
