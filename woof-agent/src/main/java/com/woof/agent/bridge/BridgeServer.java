package com.woof.agent.bridge;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

/**
 * BridgeServer — HTTP-мост на Java, тот же контракт, что у browser_bridge.cjs:
 *
 *   POST / {"action":"snapshot"|"step"|"navigate"|"raw_move"|"respawn"|"explore"}
 *   -> {ok:true, info:{...}} либо {ok:false, error:"..."}
 *
 * Бэкенд подставляется: сейчас реализован UpstreamBackend (Java впереди, Node
 * за ним — рабочий переходный вариант и он же проверяется тестами). Порт
 * игровой логики на CDP — отдельный этап, см. BRIDGE-PORT.md: там посчитан
 * объём (actions.cjs 968 строк, snapshot.cjs 456, game_client.cjs 151), и до
 * его окончания CdpBackend честно падает с внятным сообщением, а не молчит.
 */
public class BridgeServer {

    /** Источник обработки команд. */
    public interface Backend {
        JsonNode handle(String action, ObjectNode cmd) throws Exception;
        default void close() {}
    }

    private final ObjectMapper mapper = new ObjectMapper();
    private final HttpServer server;
    private final Backend backend;

    public BridgeServer(int port, Backend backend) throws IOException {
        this.backend = backend;
        this.server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
        server.createContext("/", this::handle);
        server.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(2));
    }

    public void start() {
        server.start();
        System.out.println("[Bridge] Java-мост слушает :" + server.getAddress().getPort()
                + " (бэкенд: " + backend.getClass().getSimpleName() + ")");
    }

    public void stop() { server.stop(0); backend.close(); }

    private void handle(HttpExchange ex) throws IOException {
        byte[] out;
        int code = 200;
        try {
            if ("GET".equals(ex.getRequestMethod())) {
                ObjectNode ok = mapper.createObjectNode();
                ok.put("ok", true);
                ok.put("bridge", "java");
                ok.put("backend", backend.getClass().getSimpleName());
                ok.put("hint", "POST {\"action\":\"snapshot\"}");
                out = mapper.writeValueAsBytes(ok);
            } else {
                ObjectNode cmd = readJson(ex);
                String action = cmd.path("action").asText("");
                if (action.isEmpty()) {
                    ObjectNode err = mapper.createObjectNode();
                    err.put("ok", false);
                    err.put("error", "нет поля action");
                    out = mapper.writeValueAsBytes(err);
                } else {
                    out = mapper.writeValueAsBytes(backend.handle(action, cmd));
                }
            }
        } catch (Exception e) {
            code = 500;
            ObjectNode err = mapper.createObjectNode();
            err.put("ok", false);
            err.put("error", e.getMessage() == null ? e.toString() : e.getMessage());
            out = mapper.writeValueAsBytes(err);
        }
        ex.getResponseHeaders().add("content-type", "application/json");
        ex.sendResponseHeaders(code, out.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(out); }
    }

    private ObjectNode readJson(HttpExchange ex) throws IOException {
        try (InputStream is = ex.getRequestBody()) {
            byte[] buf = is.readAllBytes();
            if (buf.length == 0) return mapper.createObjectNode();
            return (ObjectNode) mapper.readTree(new String(buf, StandardCharsets.UTF_8));
        }
    }
}
