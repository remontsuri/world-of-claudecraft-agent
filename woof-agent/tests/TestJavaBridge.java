import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sun.net.httpserver.HttpServer;
import com.woof.agent.bridge.BridgeServer;
import com.woof.agent.bridge.CdpBackend;
import com.woof.agent.bridge.UpstreamBackend;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Java-мост: контракт ответа и прозрачность к бэкенду.
 * Верхний мост (8792) -> UpstreamBackend -> заглушка ниже (8793).
 */
public class TestJavaBridge {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    public static void main(String[] args) throws Exception {
        int bad = 0;

        // Нижний «мост»: отдаёт фиксированный снимок, считает полученные действия
        final String[] seen = new String[1];
        HttpServer low = HttpServer.create(new InetSocketAddress("127.0.0.1", 8793), 0);
        low.createContext("/", ex -> {
            byte[] body = ex.getRequestBody().readAllBytes();
            JsonNode cmd = MAPPER.readTree(body.length == 0 ? "{}" : new String(body, StandardCharsets.UTF_8));
            seen[0] = cmd.path("action").asText("") + "#" + cmd.path("idx").asInt(-1);
            ObjectNode resp = MAPPER.createObjectNode();
            resp.put("ok", true);
            ObjectNode info = resp.putObject("info");
            info.put("quests_done", 7);
            info.putArray("player_pos").add(1.5).add(-2.5);
            ObjectNode player = info.putObject("player");
            player.put("hp", 100).put("maxHp", 138).put("x", 1.5).put("z", -2.5).put("level", 3);
            info.putArray("nearby");
            ObjectNode quests = info.putObject("quests");
            quests.putArray("active"); quests.putArray("ready"); quests.putArray("done");
            byte[] out = MAPPER.writeValueAsBytes(resp);
            ex.getResponseHeaders().add("content-type", "application/json");
            ex.sendResponseHeaders(200, out.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(out); }
        });
        low.start();

        BridgeServer bridge = new BridgeServer(8792, new UpstreamBackend("http://127.0.0.1:8793/"));
        bridge.start();
        try {
            JsonNode snap = post(8792, "{\"action\":\"snapshot\"}");
            if (!snap.path("ok").asBoolean() || snap.path("info").path("quests_done").asInt() != 7) {
                System.out.println("FAIL  snapshot через Java-мост -> " + snap); bad++;
            }
            JsonNode step = post(8792, "{\"action\":\"step\",\"idx\":6}");
            if (!"step#6".equals(seen[0])) { System.out.println("FAIL  idx не дошёл до бэкенда: " + seen[0]); bad++; }
            if (!step.path("ok").asBoolean()) { System.out.println("FAIL  step -> " + step); bad++; }

            JsonNode unknown = post(8792, "{\"action\":\"jump\"}");
            if (unknown.path("ok").asBoolean()) { System.out.println("FAIL  неизвестное action принято"); bad++; }

            // CDP-бэкенд обязан кричать, что логика не портирована, а не молчать
            BridgeServer cdpBridge = new BridgeServer(8794, new CdpBackend(null));
            cdpBridge.start();
            try {
                JsonNode r = post(8794, "{\"action\":\"snapshot\"}");
                String err = r.path("error").asText("");
                if (r.path("ok").asBoolean() || !err.contains("BRIDGE-PORT")) {
                    System.out.println("FAIL  CdpBackend не отчитался о неготовности: " + r); bad++;
                }
            } finally { cdpBridge.stop(); }
        } finally {
            bridge.stop();
            low.stop(0);
        }
        System.out.println(bad == 0 ? "PASS  TestJavaBridge (контракт, idx, unknown action, CdpBackend честно падает)"
                                    : "FAIL  TestJavaBridge: " + bad + " проблем");
        System.exit(bad == 0 ? 0 : 1);
    }

    private static JsonNode post(int port, String json) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL("http://127.0.0.1:" + port + "/").openConnection();
        c.setRequestMethod("POST");
        c.setRequestProperty("Content-Type", "application/json");
        c.setDoOutput(true);
        c.setConnectTimeout(3000);
        c.setReadTimeout(10000);
        try (OutputStream os = c.getOutputStream()) { os.write(json.getBytes(StandardCharsets.UTF_8)); }
        // На отказ (4xx/5xx) тело ответа лежит в errorStream: getInputStream() на нём
        // бросает IOException, и тест падал, не прочитав причину. Сервер отвечает
        // 500 + {"ok":false,"error":"..."} - клиент обязан это читать.
        int code = c.getResponseCode();
        InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
        String body = in == null ? "" : new String(in.readAllBytes(), StandardCharsets.UTF_8);
        if (body.isBlank()) {
            throw new IOException("пустой ответ от порта " + port + " (HTTP " + code + ")");
        }
        return MAPPER.readTree(body);
    }
}
