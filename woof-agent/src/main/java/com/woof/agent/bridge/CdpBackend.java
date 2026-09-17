package com.woof.agent.bridge;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * CdpBackend — мост, который сам говорит с Chrome DevTools Protocol (замена
 * browser_bridge.cjs целиком, без Node-прослойки).
 *
 * Состояние: транспорт уже есть (CdpClient), игровая логика — нет.
 * Осталось перенести: snapshot.cjs (456 строк) и actions.cjs (968 строк) —
 * план и порядок в BRIDGE-PORT.md. До этого вызовы падают с внятным текстом,
 * а не молчат: молчаливая пустышка в этом проекте уже была.
 */
public class CdpBackend implements BridgeServer.Backend {

    private static final String MESSAGE =
            "CdpBackend: игровая логика ещё не портирована (transport есть, snapshot/actions нет). "
          + "Запусти Node-мост (node browser_bridge.cjs) и используй UpstreamBackend, "
          + "либо заверши порт по плану BRIDGE-PORT.md.";

    private final CdpClient cdp;

    public CdpBackend(CdpClient cdp) {
        this.cdp = cdp;
    }

    @Override
    public JsonNode handle(String action, ObjectNode cmd) {
        throw new UnsupportedOperationException(MESSAGE);
    }

    @Override
    public void close() {
        if (cdp != null) cdp.close();
    }
}
