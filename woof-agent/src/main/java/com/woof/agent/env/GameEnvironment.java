package com.woof.agent.env;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * GameEnvironment — связь с игрой через мост (:8791).
 *
 * Контракт моста (browser_bridge.cjs / src/bridge/actions.cjs):
 *   POST / {"action":"snapshot"}                     -> {ok, info}
 *   POST / {"action":"step","idx":N}                 -> {ok, info}
 *   POST / {"action":"raw_move","kind":"forward"}    -> {ok, info}
 *   POST / {"action":"navigate","x":..,"z":..,"max_steps":N} -> {ok, info, arrived}
 *   POST / {"action":"respawn"}                      -> {ok, info}
 *   POST / {"action":"explore","steps":N}            -> {ok, info, arrived}
 *
 * Ранее этот класс возвращал кэш и пустой объект вместо запросов — то есть
 * "работал" ровно ни с чем. Теперь это настоящий HTTP-клиент.
 */
public class GameEnvironment {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private final String bridgeUrl;
    private final WorldState last = new WorldState();
    private volatile int lastHttpCode = 0;

    public GameEnvironment() {
        this(env("WOC_BRIDGE", "http://127.0.0.1:8791/"));
    }

    public GameEnvironment(String bridgeUrl) {
        this.bridgeUrl = bridgeUrl.endsWith("/") ? bridgeUrl : bridgeUrl + "/";
    }

    private static String env(String key, String def) {
        String v = System.getenv(key);
        return (v == null || v.isEmpty()) ? def : v;
    }

    public String bridgeUrl() { return bridgeUrl; }

    public WorldState getLastState() { return last; }

    public int lastHttpCode() { return lastHttpCode; }

    /** POST запроса к мосту. Бросает IOException при сетевой ошибке/не-200. */
    public JsonNode call(ObjectNode body) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(bridgeUrl).openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("Connection", "close");
        conn.setDoOutput(true);
        conn.setConnectTimeout(5000);
        conn.setReadTimeout(120_000);      // farm/navigate держат вкладку долго
        try (OutputStream os = conn.getOutputStream()) {
            os.write(MAPPER.writeValueAsBytes(body));
        }
        int code = conn.getResponseCode();
        lastHttpCode = code;
        InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        StringBuilder sb = new StringBuilder();
        if (is != null) {
            try (BufferedReader r = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                String line;
                while ((line = r.readLine()) != null) sb.append(line);
            }
        }
        String text = sb.length() == 0 ? "{}" : sb.toString();
        JsonNode node = MAPPER.readTree(text);
        if (code >= 400) {
            throw new IOException("мост вернул HTTP " + code + ": " + text);
        }
        return node;
    }

    /** Тот же вызов, но без исключений: ошибка печатается и возвращается пустой ответ. */
    public JsonNode callQuiet(ObjectNode body) {
        try {
            return call(body);
        } catch (IOException e) {
            System.err.println("[GameEnv] " + body.path("action").asText("?") + ": " + e.getMessage());
            return MAPPER.createObjectNode();
        }
    }

    private ObjectNode req(String action) {
        ObjectNode n = MAPPER.createObjectNode();
        n.put("action", action);
        return n;
    }

    public boolean health() {
        JsonNode r = callQuiet(req("health"));
        return r.path("ok").asBoolean(false) && !r.path("bridge").isMissingNode();
    }

    /** Свежий снимок мира; состояние кэшируется в last. */
    public WorldState snapshot() {
        JsonNode r = callQuiet(req("snapshot"));
        SnapshotMapper.apply(last, r.path("info"));
        return last;
    }

    /** Сырой ответ моста (для тестов и диагностики). */
    public JsonNode snapshotRaw() {
        return callQuiet(req("snapshot"));
    }

    /** Выполнить навык по индексу моста (см. SkillIndex). */
    public JsonNode step(int skillIdx) {
        return step(skillIdx, null);
    }

    /** Выполнить навык с контекстом (targetMobId / mobId / questId / nodeType / buyItemId). */
    public JsonNode step(int skillIdx, ObjectNode ctx) {
        ObjectNode n = (ctx == null ? MAPPER.createObjectNode() : ctx.deepCopy());
        n.put("action", "step");
        n.put("idx", skillIdx);
        return callQuiet(n);
    }

    public JsonNode rawMove(String kind) {
        ObjectNode n = req("raw_move");
        n.put("kind", kind);
        return callQuiet(n);
    }

    public JsonNode respawn() {
        return callQuiet(req("respawn"));
    }

    public JsonNode explore(int steps) {
        ObjectNode n = req("explore");
        n.put("steps", steps);
        return callQuiet(n);
    }

    /** Идти к точке; возвращает true, если мост отчитался arrived. */
    public boolean navigate(double x, double z, int maxSteps) {
        return navigateRaw(x, z, maxSteps).path("arrived").asBoolean(false);
    }

    public JsonNode navigateRaw(double x, double z, int maxSteps) {
        ObjectNode n = req("navigate");
        n.put("x", x);
        n.put("z", z);
        n.put("max_steps", maxSteps);
        return callQuiet(n);
    }

    public void close() {
        // HTTP без keep-alive: закрывать нечего
    }
}
