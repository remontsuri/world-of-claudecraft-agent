package com.woof.agent.bridge;

/**
 * BridgeMain — запуск Java-моста на :8791.
 *
 *   --upstream URL  мост Java впереди, Node за ним (рабочий вариант сейчас)
 *   без --upstream   чистый CDP-мост (транспорт есть, игровая логика — в работе)
 */
public class BridgeMain {
    public static void main(String[] args) throws Exception {
        int port = 8791;
        String upstream = null;
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--port":     port = Integer.parseInt(args[++i]); break;
                case "--upstream": upstream = args[++i]; break;
                default: break;
            }
        }
        BridgeServer.Backend backend = (upstream != null)
                ? new UpstreamBackend(upstream)
                : new CdpBackend(new CdpClient());
        System.out.println("[Bridge] backend=" + backend.getClass().getSimpleName()
                + (upstream != null ? " upstream=" + upstream : ""));
        new BridgeServer(port, backend).start();
        Thread.currentThread().join();
    }
}
