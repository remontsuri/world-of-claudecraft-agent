import com.woof.agent.bridge.CdpClient;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.List;

/**
 * Тест CDP-транспорта без браузера: поднимается tools/fake_cdp.cjs
 * (две вкладки — мёртвая и живая) и проверяется ровно то, что ломалось в
 * заглушке: выбор живой вкладки, повтор после потери контекста, health.
 */
public class TestCdpClient {
    public static void main(String[] args) throws Exception {
        String root = System.getProperty("repo.root", ".");
        int httpPort = 9231, wsPort = 9232;
        Process fake = new ProcessBuilder("node", root + "/tools/fake_cdp.cjs",
                String.valueOf(httpPort), String.valueOf(wsPort))
                .directory(new java.io.File(root))
                .inheritIO()
                .start();
        int bad = 0;
        try {
            if (!waitPort("127.0.0.1", httpPort, 8000)) {
                System.out.println("FAIL  fake CDP не поднялся");
                System.exit(1);
            }
            CdpClient cdp = new CdpClient("http://127.0.0.1:" + httpPort,
                    List.of("localhost:5173"), 5000);

            // 1. health: мост есть, вкладка найдена, игра живая
            ObjectNode h = cdp.health();
            if (!(h.path("bridge").asBoolean() && h.path("page").asBoolean() && h.path("game").asBoolean())) {
                System.out.println("FAIL  health=" + h); bad++;
            }

            // 2. живая вкладка выбрана, а не первая попавшаяся (мёртвая идёт первой)
            if (!cdp.acquirePage()) { System.out.println("FAIL  acquirePage false"); bad++; }
            String url = cdp.currentUrl();
            if (url == null || !url.contains("/live")) {
                System.out.println("FAIL  выбрана не живая вкладка: " + url); bad++;
            }

            // 3. обычное исполнение JS
            Object v = cdp.evaluate("(function(){return 40+2;})()");
            if (!(v instanceof Number) || ((Number) v).intValue() != 42) {
                System.out.println("FAIL  evaluate -> " + v); bad++;
            }

            // 4. потеря контекста (перезагрузка SPA): первый вызов падает,
            //    клиент обязан пере-захватить вкладку и повторить
            Object retry = cdp.evaluate("(function(){return 'RETRY_ONCE';})()");
            if (!"recovered".equals(retry)) {
                System.out.println("FAIL  повтор после потери контекста -> " + retry); bad++;
            }

            // 5. вызов функции с аргументами (как snapshot.js/actions.js)
            Object sum = cdp.callFunction("function(a,b){return a+b;}", 20, 22);
            if (!(sum instanceof Number) || ((Number) sum).intValue() != 42) {
                System.out.println("FAIL  callFunction -> " + sum); bad++;
            }
            cdp.close();
        } finally {
            fake.destroy();
        }
        System.out.println(bad == 0 ? "PASS  TestCdpClient (живая вкладка + повтор + evaluate)"
                                    : "FAIL  TestCdpClient: " + bad + " проблем");
        System.exit(bad == 0 ? 0 : 1);
    }

    private static boolean waitPort(String host, int port, long ms) {
        long end = System.currentTimeMillis() + ms;
        while (System.currentTimeMillis() < end) {
            try (Socket s = new Socket()) {
                s.connect(new InetSocketAddress(host, port), 200);
                return true;
            } catch (Exception e) {
                try { Thread.sleep(100); } catch (InterruptedException ignored) { }
            }
        }
        return false;
    }
}
