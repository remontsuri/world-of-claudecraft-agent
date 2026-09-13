package com.woof.agent.mcp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;

/**
 * WoOF MCP Server — HTTP JSON-RPC 2.0
 * Tools: status, start, stop, logs, config, build, test
 * Run on port 8792
 */
public class WoofMcpServer {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private final int port;
    private ServerSocket serverSocket;
    private volatile boolean running = true;

    public WoofMcpServer(int port) {
        this.port = port;
    }

    public void start() throws IOException {
        serverSocket = new ServerSocket(port);
        System.out.println("[MCP] WoOF MCP Server listening on :" + port);

        while (running) {
            try {
                Socket client = serverSocket.accept();
                handleClient(client);
            } catch (IOException e) {
                if (running) e.printStackTrace();
            }
        }
    }

    private void handleClient(Socket client) {
        try (BufferedReader in = new BufferedReader(new InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8));
             OutputStream out = client.getOutputStream()) {

            // Read HTTP request
            StringBuilder request = new StringBuilder();
            String line;
            int contentLength = 0;
            while ((line = in.readLine()) != null && !line.isEmpty()) {
                request.append(line).append("\r\n");
                if (line.toLowerCase().startsWith("content-length:")) {
                    contentLength = Integer.parseInt(line.substring(15).trim());
                }
            }

            // Read body
            char[] body = new char[contentLength];
            in.read(body, 0, contentLength);
            String bodyStr = new String(body);

            // Handle JSON-RPC
            String response = handleRpc(bodyStr);

            // Send HTTP response
            byte[] respBytes = response.getBytes(StandardCharsets.UTF_8);
            String httpResponse = "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: application/json\r\n" +
                    "Content-Length: " + respBytes.length + "\r\n" +
                    "Access-Control-Allow-Origin: *\r\n" +
                    "\r\n";
            out.write(httpResponse.getBytes(StandardCharsets.UTF_8));
            out.write(respBytes);
            out.flush();
        } catch (Exception e) {
            // ignore client errors
        }
    }

    private String handleRpc(String body) {
        try {
            ObjectNode request = (ObjectNode) MAPPER.readTree(body);
            String method = request.has("method") ? request.get("method").asText() : "";

            ObjectNode response = MAPPER.createObjectNode();
            response.put("jsonrpc", "2.0");
            if (request.has("id")) {
                response.set("id", request.get("id"));
            }

            switch (method) {
                case "initialize":
                    response.set("result", handleInitialize());
                    break;
                case "tools/list":
                    response.set("result", listTools());
                    break;
                case "tools/call":
                    JsonNode paramsNode = request.get("params");
                    response.set("result", callTool((ObjectNode) (paramsNode != null ? paramsNode : MAPPER.createObjectNode())));
                    break;
                default:
                    response.put("error_code", -32601);
                    response.put("error_message", "Method not found: " + method);
            }

            return MAPPER.writeValueAsString(response);
        } catch (Exception e) {
            ObjectNode err = MAPPER.createObjectNode();
            err.put("jsonrpc", "2.0");
            err.put("error_code", -32603);
            err.put("error_message", e.getMessage());
            try {
                return MAPPER.writeValueAsString(err);
            } catch (Exception ex) {
                return "{\"jsonrpc\":\"2.0\",\"error\":-32603}";
            }
        }
    }

    private ObjectNode handleInitialize() {
        ObjectNode result = MAPPER.createObjectNode();
        result.put("name", "woof-agent-mcp");
        result.put("version", "1.0.0");

        ObjectNode serverInfo = MAPPER.createObjectNode();
        serverInfo.put("name", "woof-agent");
        serverInfo.put("version", "1.0.0");
        result.set("serverInfo", serverInfo);

        result.put("instructions", "WoOF Agent MCP — Java autonomous agent for World of ClaudeCraft. " +
                "Provides tools to manage and monitor the agent lifecycle.");

        ArrayNode capabilities = MAPPER.createArrayNode();
        ObjectNode tools = MAPPER.createObjectNode();
        tools.put("tools", true);
        capabilities.add(tools);
        result.set("capabilities", capabilities);

        return result;
    }

    private ObjectNode listTools() {
        ObjectNode result = MAPPER.createObjectNode();
        ArrayNode tools = MAPPER.createArrayNode();

        tools.add(tool("woof_status", "Get current agent status: HP, position, kills, deaths, FSM state, active quest",
                params(), required("")));
        tools.add(tool("woof_logs", "Get recent agent log entries",
                params("lines", "number"), required("lines")));
        tools.add(tool("woof_config", "Get or set configuration value",
                params("key", "string", "value", "string"), required("key")));
        tools.add(tool("woof_build", "Compile the Java project",
                params(), required("")));
        tools.add(tool("woof_test", "Run test suite",
                params("test_name", "string"), required("")));
        tools.add(tool("woof_game_state", "Get live game snapshot from bridge",
                params(), required("")));
        tools.add(tool("woof_execute_action", "Execute a single game action",
                params("action", "string", "target_id", "string"), required("action")));

        result.set("tools", tools);
        return result;
    }

    private ObjectNode callTool(ObjectNode params) {
        String name = params.has("name") ? params.get("name").asText() : "";
        ObjectNode arguments = params.has("arguments") ? (ObjectNode) params.get("arguments") : MAPPER.createObjectNode();

        ObjectNode result = MAPPER.createObjectNode();
        ArrayNode content = MAPPER.createArrayNode();

        ObjectNode textContent = MAPPER.createObjectNode();
        textContent.put("type", "text");

        switch (name) {
            case "woof_status":
                textContent.put("text", getStatus());
                break;
            case "woof_logs":
                int lines = arguments.has("lines") ? arguments.get("lines").asInt(50) : 50;
                textContent.put("text", getLogs(lines));
                break;
            case "woof_config":
                String key = arguments.has("key") ? arguments.get("key").asText() : "";
                String value = arguments.has("value") ? arguments.get("value").asText() : null;
                textContent.put("text", handleConfig(key, value));
                break;
            case "woof_build":
                textContent.put("text", runBuild());
                break;
            case "woof_test":
                String testName = arguments.has("test_name") ? arguments.get("test_name").asText() : "";
                textContent.put("text", runTest(testName));
                break;
            case "woof_game_state":
                textContent.put("text", getGameState());
                break;
            case "woof_execute_action":
                String action = arguments.has("action") ? arguments.get("action").asText() : "";
                String targetId = arguments.has("target_id") ? arguments.get("target_id").asText() : null;
                textContent.put("text", executeAction(action, targetId));
                break;
            default:
                textContent.put("text", "Unknown tool: " + name);
        }

        content.add(textContent);
        result.set("content", content);
        return result;
    }

    // === Tool Implementations ===

    private String getStatus() {
        return "WoOF Agent v1.0.0\n" +
                "Stack: Java 17, Jackson, Java-WebSocket\n" +
                "Architecture: Voyager Loop\n" +
                "Bridge: :8791\n" +
                "MCP: :8792\n";
    }

    private String getLogs(int lines) {
        return "Log reading not yet implemented (lines=" + lines + ")";
    }

    private String handleConfig(String key, String value) {
        if (key.isEmpty()) return "Usage: config [key] [value]";
        if (value == null) return "Config[" + key + "] = <not implemented>";
        return "Config[" + key + "] = " + value + " (set)";
    }

    private String runBuild() {
        try {
            ProcessBuilder pb = new ProcessBuilder(
                    "C:/Program Files/Java/jdk-17.0.20.1+1/bin/javac",
                    "-cp", "libs/jackson-databind.jar;libs/jackson-core.jar;libs/jackson-annotations.jar;libs/java-websocket.jar",
                    "-d", "build/classes",
                    "@sources.txt"
            );
            pb.directory(new File("D:/world-of-claudecraft/woof-agent"));
            pb.redirectErrorStream(true);
            Process p = pb.start();
            BufferedReader reader = new BufferedReader(new InputStreamReader(p.getInputStream()));
            StringBuilder output = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                output.append(line).append("\n");
            }
            p.waitFor();
            return "BUILD " + (p.exitValue() == 0 ? "SUCCESS" : "FAILED") + "\n" + output;
        } catch (Exception e) {
            return "BUILD ERROR: " + e.getMessage();
        }
    }

    private String runTest(String testName) {
        return "Test runner not yet implemented" + (testName.isEmpty() ? "" : ": " + testName);
    }

    private String getGameState() {
        try {
            URL url = new URL("http://127.0.0.1:8791/snapshot");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(3000);
            BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) sb.append(line);
            return sb.toString();
        } catch (Exception e) {
            return "Bridge unreachable: " + e.getMessage();
        }
    }

    private String executeAction(String action, String targetId) {
        return "Action execution not yet implemented: " + action + (targetId != null ? " target=" + targetId : "");
    }

    // === Helpers ===

    private ObjectNode tool(String name, String description, ObjectNode inputSchema, java.util.List<String> required) {
        ObjectNode tool = MAPPER.createObjectNode();
        tool.put("name", name);
        tool.put("description", description);
        tool.set("inputSchema", inputSchema);
        if (!required.isEmpty()) {
            ArrayNode req = MAPPER.createArrayNode();
            required.forEach(req::add);
            inputSchema.set("required", req);
        }
        return tool;
    }

    private ObjectNode params(String... keysAndTypes) {
        ObjectNode schema = MAPPER.createObjectNode();
        schema.put("type", "object");
        ObjectNode properties = MAPPER.createObjectNode();

        for (int i = 0; i < keysAndTypes.length; i += 2) {
            if (i + 1 < keysAndTypes.length) {
                ObjectNode prop = MAPPER.createObjectNode();
                prop.put("type", keysAndTypes[i + 1]);
                prop.put("description", keysAndTypes[i]);
                properties.set(keysAndTypes[i], prop);
            }
        }

        schema.set("properties", properties);
        return schema;
    }

    private java.util.List<String> required(String commaSeparated) {
        java.util.List<String> list = new java.util.ArrayList<>();
        if (!commaSeparated.isEmpty()) {
            for (String s : commaSeparated.split(",")) {
                list.add(s.trim());
            }
        }
        return list;
    }

    // === Main ===

    public static void main(String[] args) throws Exception {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 8792;
        new WoofMcpServer(port).start();
    }
}
