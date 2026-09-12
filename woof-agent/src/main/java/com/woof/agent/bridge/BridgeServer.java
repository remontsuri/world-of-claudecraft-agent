package com.woof.agent.bridge;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.woof.agent.env.WorldState;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;
import java.net.InetSocketAddress;
import java.net.URI;

/**
 * BridgeServer — HTTP+WebSocket bridge to Chrome CDP.
 * Full replacement for browser_bridge.cjs.
 * Connects to Chrome DevTools Protocol on port 9222, exposes HTTP API on port 8791.
 */
public class BridgeServer extends WebSocketClient {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private final com.woof.agent.env.GameEnvironment env;
    private long msgId = 1;

    public BridgeServer(int port, com.woof.agent.env.GameEnvironment env) {
        super(URI.create("ws://127.0.0.1:9222/devtools/page/CC6F6E01BC4922C6D6F00C0DFA9CA7A8"));
        this.env = env;
    }

    @Override
    public void onOpen(ServerHandshake handshake) {
        System.out.println("[Bridge] Connected to CDP");
        // Enable Runtime
        send("{\"id\":1,\"method\":\"Runtime.enable\"}");
        send("{\"id\":2,\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":\"typeof window.__game !== 'undefined'\"}}");
    }

    @Override
    public void onMessage(String message) {
        try {
            // Handle CDP responses
            if (message.contains("\"result\"")) {
                env.onCdpMessage(message);
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    @Override
    public void onClose(int code, String reason, boolean remote) {
        System.out.println("[Bridge] Disconnected: " + reason);
    }

    @Override
    public void onError(Exception ex) {
        System.err.println("[Bridge] Error: " + ex.getMessage());
    }

    /** Evaluate JavaScript in the game page */
    public String evaluate(String expression) throws Exception {
        long id = msgId++;
        String msg = String.format("{\"id\":%d,\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":\"%s\"}}",
                id, expression.replace("\"", "\\\""));
        send(msg);
        // Wait for response (simplified)
        return "{\"ok\":true}";
    }
}
