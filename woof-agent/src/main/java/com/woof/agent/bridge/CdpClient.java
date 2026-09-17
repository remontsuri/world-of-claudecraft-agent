package com.woof.agent.bridge;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * CdpClient — транспорт к запущенному Chrome (--remote-debugging-port=9222).
 * Порт src/bridge/game_client.cjs: найти ЖИВУЮ вкладку игры, исполнять в ней JS,
 * переживать перезагрузку страницы (SPA), отчитываться о здоровье.
 *
 * Игровой логики здесь нет — только транспорт: снимок и навыки приходят
 * строками JS снаружи (snapshot.js / actions.js), как в Node-версии.
 *
 * В отличие от прежней заглушки: вкладка ищется через /json/list по признаку
 * живого игрока, ответы сопоставляются по id запроса. Зашитого GUID вкладки нет.
 */
public class CdpClient {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String DEFAULT_CDP = "http://127.0.0.1:9222";
    private static final String[] DEFAULT_TAB_MATCH = {
            "worldofclaudecraft", "localhost:5173", "127.0.0.1:5173"
    };

    /** Проверка «в этой вкладке действительно живёт игрок» (аналог acquirePage). */
    private static final String LIVE_PROBE =
            "(function(){var g=window.__game;if(!g||!g.sim)return false;var s=g.sim;"
          + "var pid=s.primaryId;if(typeof pid!=='number'&&typeof pid!=='string')return false;"
          + "var e=s.entities&&(s.entities.get?s.entities.get(pid):s.entities[pid]);"
          + "return !!e;})()";

    private static final String RELEASE_INPUTS =
            "(function(){try{window.__game.controller.stop();}catch(e){}return true;})()";

    private final String cdpUrl;
    private final List<String> tabMatch;
    private final long evalTimeoutMs;

    private HttpClient http;
    private Page page;

    public CdpClient() {
        this(System.getenv().getOrDefault("WOC_CDP", DEFAULT_CDP), tabPatterns(), 20_000);
    }

    public CdpClient(String cdpUrl, List<String> tabMatch, long evalTimeoutMs) {
        this.cdpUrl = cdpUrl.endsWith("/") ? cdpUrl.substring(0, cdpUrl.length() - 1) : cdpUrl;
        this.tabMatch = tabMatch;
        this.evalTimeoutMs = evalTimeoutMs;
    }

    private static List<String> tabPatterns() {
        String env = System.getenv("WOC_TAB_MATCH");
        List<String> out = new ArrayList<>();
        if (env != null && !env.isEmpty()) {
            for (String p : env.split(",")) if (!p.trim().isEmpty()) out.add(p.trim());
        } else {
            for (String p : DEFAULT_TAB_MATCH) out.add(p);
        }
        return out;
    }

    // ------------------------------------------------------------------ вкладка

    /** Список целей браузера: GET /json/list. */
    public ArrayNode listTargets() throws Exception {
        HttpClient h = (http == null) ? (http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5)).build()) : http;
        HttpRequest req = HttpRequest.newBuilder(URI.create(cdpUrl + "/json/list"))
                .timeout(Duration.ofSeconds(5)).GET().build();
        HttpResponse<String> resp = h.send(req, HttpResponse.BodyHandlers.ofString());
        JsonNode node = MAPPER.readTree(resp.body());
        if (!node.isArray()) throw new IllegalStateException("CDP вернул не список целей: " + resp.body());
        return (ArrayNode) node;
    }

    private boolean tabMatches(String url) {
        if (url == null) return false;
        for (String p : tabMatch) if (url.contains(p)) return true;
        return false;
    }

    /** Найти живую вкладку игры (как acquirePage: сначала URL, потом проба на игрока). */
    public boolean acquirePage() {
        try {
            for (JsonNode t : listTargets()) {
                if (!"page".equals(t.path("type").asText())) continue;
                if (!tabMatches(t.path("url").asText())) continue;
                String ws = t.path("webSocketDebuggerUrl").asText("");
                if (ws.isEmpty()) continue;
                Page candidate = new Page(ws, t.path("url").asText());
                try {
                    Object value = candidate.evaluateRaw(LIVE_PROBE, 5_000);
                    if (value instanceof Boolean && (Boolean) value) {
                        closePage();
                        this.page = candidate;
                        return true;
                    }
                } catch (Exception ignore) {
                    // контекст мёртв — пробуем следующую вкладку
                }
                candidate.close();
            }
        } catch (Exception e) {
            System.err.println("[CdpClient] список целей недоступен: " + e.getMessage());
        }
        page = null;
        return false;
    }

    private void closePage() {
        if (page != null) { page.close(); page = null; }
    }

    /** Исполнить JS в живом контексте; 3 попытки с пере-захватом вкладки. */
    public Object evaluate(String expression) {
        for (int attempt = 0; attempt < 3; attempt++) {
            try {
                if (page == null && !acquirePage()) return null;
                return page.evaluateRaw(expression, evalTimeoutMs);
            } catch (Exception e) {
                System.err.println("[CdpClient] evaluate, попытка " + (attempt + 1) + ": " + e.getMessage());
                closePage();                      // перезагрузка страницы убивает контекст
                acquirePage();
            }
        }
        return null;
    }

    /** Вызов JS-функции с аргументами: (function(){ ... })(arg0, arg1, ...). */
    public Object callFunction(String jsFunction, Object... args) {
        StringBuilder sb = new StringBuilder("(").append(jsFunction).append(")(");
        for (int i = 0; i < args.length; i++) {
            if (i > 0) sb.append(',');
            try {
                sb.append(MAPPER.writeValueAsString(args[i]));
            } catch (Exception e) {
                sb.append("null");
            }
        }
        return evaluate(sb.append(')').toString());
    }

    /** Вызвать JS-функцию, ожидая JSON-объект; null, если вернулось не то. */
    public JsonNode callFunctionForJson(String jsFunction, Object... args) {
        Object value = callFunction(jsFunction, args);
        if (value == null) return null;
        try {
            return MAPPER.valueToTree(value);
        } catch (Exception e) {
            return null;
        }
    }

    /** {bridge, page, game} — как health() в Node-клиенте. */
    public ObjectNode health() {
        ObjectNode out = MAPPER.createObjectNode();
        boolean bridge = false, pageFound = false, game = false;
        try {
            listTargets();
            bridge = true;
        } catch (Exception ignored) { }
        if (bridge && acquirePage()) {
            pageFound = true;
            try {
                Object live = page != null ? page.evaluateRaw(LIVE_PROBE, 5_000) : null;
                game = Boolean.TRUE.equals(live);
            } catch (Exception e) {
                game = false;
            }
        }
        out.put("bridge", bridge);
        out.put("page", pageFound);
        out.put("game", game);
        return out;
    }

    /** Отпустить удержанный ввод, чтобы персонаж не бежал после остановки моста. */
    public void releaseInputs() {
        try {
            for (JsonNode t : listTargets()) {
                if (!"page".equals(t.path("type").asText())) continue;
                if (!tabMatches(t.path("url").asText())) continue;
                String ws = t.path("webSocketDebuggerUrl").asText("");
                if (ws.isEmpty()) continue;
                Page p = new Page(ws, t.path("url").asText());
                try { p.evaluateRaw(RELEASE_INPUTS, 3_000); } catch (Exception ignored) { }
                p.close();
            }
        } catch (Exception ignored) { }
    }

    public String currentUrl() { return page == null ? null : page.url; }

    public void close() {
        closePage();
        http = null;
    }

    // ------------------------------------------------------------- вкладка (WS)

    /** Одно WS-соединение с вкладкой: запросы по id, ожидание ответа. */
    private static final class Page {
        private final String url;
        private final WebSocketClient ws;
        private final AtomicLong nextId = new AtomicLong(1);
        private final Map<Long, CompletableFuture<JsonNode>> pending = new ConcurrentHashMap<>();

        Page(String wsUrl, String url) throws Exception {
            this.url = url;
            this.ws = new WebSocketClient(URI.create(wsUrl)) {
                @Override public void onOpen(ServerHandshake h) { }
                @Override public void onMessage(String message) {
                    try {
                        JsonNode node = MAPPER.readTree(message);
                        if (!node.hasNonNull("id")) return;         // события игнорируем
                        CompletableFuture<JsonNode> f = pending.remove(node.get("id").asLong());
                        if (f != null) f.complete(node);
                    } catch (Exception ignored) { }
                }
                @Override public void onClose(int code, String reason, boolean remote) {
                    failAll("соединение закрыто: " + reason);
                }
                @Override public void onError(Exception ex) {
                    failAll("ошибка WS: " + ex.getMessage());
                }
                private void failAll(String why) {
                    for (CompletableFuture<JsonNode> f : pending.values()) {
                        f.completeExceptionally(new IllegalStateException(why));
                    }
                    pending.clear();
                }
            };
            if (!ws.connectBlocking(5, TimeUnit.SECONDS)) {
                throw new IllegalStateException("не удалось подключиться к вкладке " + wsUrl);
            }
            try { send("Runtime.enable", MAPPER.createObjectNode(), 5_000); } catch (Exception ignored) { }
        }

        JsonNode send(String method, ObjectNode params, long timeoutMs) throws Exception {
            long id = nextId.getAndIncrement();
            ObjectNode msg = MAPPER.createObjectNode();
            msg.put("id", id);
            msg.put("method", method);
            msg.set("params", params == null ? MAPPER.createObjectNode() : params);
            CompletableFuture<JsonNode> future = new CompletableFuture<>();
            pending.put(id, future);
            ws.send(MAPPER.writeValueAsString(msg));
            try {
                return future.get(timeoutMs, TimeUnit.MILLISECONDS);
            } catch (java.util.concurrent.TimeoutException e) {
                pending.remove(id);
                throw new IllegalStateException("таймаут CDP " + method + " (" + timeoutMs + " мс)");
            }
        }

        /** Runtime.evaluate с returnByValue: возвращает значение или бросает. */
        Object evaluateRaw(String expression, long timeoutMs) throws Exception {
            ObjectNode params = MAPPER.createObjectNode();
            params.put("expression", expression);
            params.put("returnByValue", true);
            params.put("awaitPromise", true);
            JsonNode resp = send("Runtime.evaluate", params, timeoutMs);
            if (resp.has("error")) {
                // Протокольная ошибка CDP (например "Cannot find context with specified id"
                // после перезагрузки страницы) обязана быть исключением: молчаливый null
                // заставлял вызывающий код считать, что игра ответила.
                throw new IllegalStateException("CDP error: "
                        + resp.path("error").path("message").asText(resp.path("error").toString()));
            }
            JsonNode res = resp.path("result");
            if (res.has("exceptionDetails")) {
                throw new IllegalStateException("JS исключение: "
                        + res.path("exceptionDetails").path("text").asText("?"));
            }
            JsonNode remote = res.path("result");
            if (remote.isMissingNode() || remote.get("value") == null || remote.get("value").isNull()) return null;
            return MAPPER.convertValue(remote.get("value"), Object.class);
        }

        void close() {
            try { ws.closeBlocking(); } catch (Exception ignored) { }
        }
    }
}
