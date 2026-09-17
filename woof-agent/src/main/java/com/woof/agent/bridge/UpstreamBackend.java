package com.woof.agent.bridge;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.woof.agent.env.GameEnvironment;

/**
 * UpstreamBackend — Java-мост поверх уже работающего моста (Node).
 *
 * Нужен, чтобы переход на Java шёл постепенно: агент и внешние клиенты видят
 * один и тот же контракт на :8791, а игровая логика пока живёт там, где она
 * отлажена. Когда CdpBackend будет портирован, бэкенд меняется одной строкой.
 */
public class UpstreamBackend implements BridgeServer.Backend {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private final GameEnvironment upstream;

    public UpstreamBackend(String upstreamUrl) {
        this.upstream = new GameEnvironment(upstreamUrl);
    }

    @Override
    public JsonNode handle(String action, ObjectNode cmd) throws Exception {
        switch (action) {
            case "snapshot":  return upstream.snapshotRaw();
            case "health": {
                ObjectNode ok = MAPPER.createObjectNode();
                ok.put("ok", upstream.health());
                ok.put("bridge", "java->upstream");
                ok.put("upstream", upstream.bridgeUrl());
                return ok;
            }
            case "step":      return upstream.step(cmd.path("idx").asInt(0), cmd);
            case "raw_move":  return upstream.rawMove(cmd.path("kind").asText("forward"));
            case "respawn":   return upstream.respawn();
            case "explore":   return upstream.explore(cmd.path("steps").asInt(10));
            case "navigate":  return upstream.navigateRaw(cmd.path("x").asDouble(0),
                                                          cmd.path("z").asDouble(0),
                                                          cmd.path("max_steps").asInt(80));
            default: {
                ObjectNode err = MAPPER.createObjectNode();
                err.put("ok", false);
                err.put("error", "неизвестное действие: " + action);
                return err;
            }
        }
    }
}
