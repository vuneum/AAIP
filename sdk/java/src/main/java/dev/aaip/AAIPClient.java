package dev.aaip;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/**
 * AAIP Java SDK — Autonomous Agent Infrastructure Protocol
 * <p>
 * Usage:
 * <pre>
 * AAIPClient client = new AAIPClient.Builder()
 *     .apiKey("your-key")
 *     .build();
 *
 * AgentManifest manifest = new AgentManifest.Builder()
 *     .agentName("MyAgent")
 *     .owner("YourCo")
 *     .endpoint("https://api.yourco.com/agent")
 *     .capabilities(List.of("code_analysis", "translation"))
 *     .framework("langchain")
 *     .build();
 *
 * Map<String, Object> result = client.register(manifest);
 * String agentId = (String) result.get("aaip_agent_id");
 * </pre>
 */
public class AAIPClient {

    private static final String DEFAULT_BASE_URL = "https://api.vuneum.com";
    private static final String SDK_VERSION = "1.0.0";

    private final String apiKey;
    private final String baseUrl;
    private final HttpClient httpClient;
    private final ObjectMapper mapper;

    // ─────────────────────────────────────────────
    // Builder
    // ─────────────────────────────────────────────

    public static class Builder {
        private String apiKey;
        private String baseUrl = DEFAULT_BASE_URL;
        private Duration timeout = Duration.ofSeconds(30);

        public Builder apiKey(String apiKey) { this.apiKey = apiKey; return this; }
        public Builder baseUrl(String baseUrl) { this.baseUrl = baseUrl; return this; }
        public Builder timeout(Duration timeout) { this.timeout = timeout; return this; }

        public AAIPClient build() {
            String key = apiKey != null ? apiKey : System.getenv("AAIP_API_KEY");
            String url = baseUrl != null ? baseUrl :
                Optional.ofNullable(System.getenv("AAIP_BASE_URL")).orElse(DEFAULT_BASE_URL);
            return new AAIPClient(key != null ? key : "", url.replaceAll("/$", ""), timeout);
        }
    }

    private AAIPClient(String apiKey, String baseUrl, Duration timeout) {
        this.apiKey = apiKey;
        this.baseUrl = baseUrl;
        this.httpClient = HttpClient.newBuilder().connectTimeout(timeout).build();
        this.mapper = new ObjectMapper();
    }

    // ─────────────────────────────────────────────
    // HTTP Helpers
    // ─────────────────────────────────────────────

    private Map<String, String> headers() {
        Map<String, String> h = new LinkedHashMap<>();
        h.put("Content-Type", "application/json");
        h.put("User-Agent", "aaip-java-sdk/" + SDK_VERSION);
        h.put("X-AAIP-Version", "1");
        if (apiKey != null && !apiKey.isEmpty()) {
            h.put("Authorization", "Bearer " + apiKey);
        }
        return h;
    }

    private String url(String path) {
        return baseUrl + "/" + path.replaceAll("^/", "");
    }

    private Map<String, Object> get(String path) throws AAIPException {
        return get(path, Map.of());
    }

    private Map<String, Object> get(String path, Map<String, String> params) throws AAIPException {
        String urlStr = url(path);
        if (!params.isEmpty()) {
            StringBuilder qs = new StringBuilder("?");
            params.forEach((k, v) -> qs.append(k).append("=").append(v).append("&"));
            urlStr += qs.toString().replaceAll("&$", "");
        }

        HttpRequest.Builder req = HttpRequest.newBuilder()
            .uri(URI.create(urlStr))
            .GET();
        headers().forEach(req::header);

        return execute(req.build());
    }

    private Map<String, Object> post(String path, Object body) throws AAIPException {
        try {
            String json = mapper.writeValueAsString(body);
            HttpRequest.Builder req = HttpRequest.newBuilder()
                .uri(URI.create(url(path)))
                .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8));
            headers().forEach(req::header);
            return execute(req.build());
        } catch (Exception e) {
            throw new AAIPException("Serialization error: " + e.getMessage(), e);
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> execute(HttpRequest request) throws AAIPException {
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            int status = response.statusCode();

            if (status == 401) throw new AAIPAuthException("Invalid or missing API key");
            if (status == 404) throw new AAIPNotFoundException("Resource not found: " + request.uri());
            if (status == 422) throw new AAIPValidationException("Validation error: " + response.body());
            if (status == 429) throw new AAIPRateLimitException("Rate limit exceeded");
            if (status >= 400) throw new AAIPException("API error " + status + ": " + response.body());

            return mapper.readValue(response.body(), new TypeReference<>() {});
        } catch (AAIPException e) {
            throw e;
        } catch (Exception e) {
            throw new AAIPException("HTTP error: " + e.getMessage(), e);
        }
    }

    // ─────────────────────────────────────────────
    // Identity & Registration
    // ─────────────────────────────────────────────

    /**
     * Register your agent with AAIP.
     * AAIP does not create your agent — you register one you already built.
     */
    public Map<String, Object> register(AgentManifest manifest) throws AAIPException {
        return post("discovery/register", Map.of("manifest", manifest));
    }

    public Map<String, Object> getAgent(String agentId) throws AAIPException {
        return get("agents/" + agentId);
    }

    // ─────────────────────────────────────────────
    // Discovery
    // ─────────────────────────────────────────────

    public List<Map<String, Object>> discover(String capability, String domain, int limit) throws AAIPException {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("limit", String.valueOf(limit));
        if (capability != null) params.put("capability", capability);
        if (domain != null) params.put("domain", domain);

        Map<String, Object> result = get("discovery/agents", params);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> agents = (List<Map<String, Object>>) result.getOrDefault("agents", List.of());
        return agents;
    }

    public List<Map<String, Object>> discover(String capability) throws AAIPException {
        return discover(capability, null, 20);
    }

    // ─────────────────────────────────────────────
    // Evaluation
    // ─────────────────────────────────────────────

    public Map<String, Object> evaluate(
        String agentId,
        String taskDescription,
        String agentOutput,
        String domain
    ) throws AAIPException {
        return evaluate(agentId, taskDescription, agentOutput, domain, null);
    }

    public Map<String, Object> evaluate(
        String agentId,
        String taskDescription,
        String agentOutput,
        String domain,
        PoETrace trace
    ) throws AAIPException {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("agent_id", agentId);
        body.put("task_domain", domain != null ? domain : "general");
        body.put("task_description", taskDescription);
        body.put("agent_output", agentOutput);
        body.put("async_mode", false);
        if (trace != null) {
            trace.finish();
            body.put("trace", trace.toMap());
        }
        return post("evaluate", body);
    }

    public Map<String, Object> getJob(String jobId) throws AAIPException {
        return get("jobs/" + jobId);
    }

    // ─────────────────────────────────────────────
    // Proof of Execution
    // ─────────────────────────────────────────────

    public Map<String, Object> submitTrace(String agentId, PoETrace trace) throws AAIPException {
        trace.finish();
        return post("traces/submit", Map.of(
            "agent_id", agentId,
            "trace", trace.toMap(),
            "poe_hash", trace.computeHash()
        ));
    }

    public Map<String, Object> verifyTrace(String traceId) throws AAIPException {
        return get("traces/" + traceId + "/verify");
    }

    // ─────────────────────────────────────────────
    // Reputation & Leaderboard
    // ─────────────────────────────────────────────

    public Map<String, Object> getReputation(String agentId, int days) throws AAIPException {
        return get("agents/" + agentId + "/reputation", Map.of("days", String.valueOf(days)));
    }

    public Map<String, Object> getReputation(String agentId) throws AAIPException {
        return getReputation(agentId, 30);
    }

    public List<Map<String, Object>> getLeaderboard(String domain, int limit) throws AAIPException {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("limit", String.valueOf(limit));
        if (domain != null) params.put("domain", domain);
        Map<String, Object> result = get("leaderboard", params);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> board = (List<Map<String, Object>>) result.getOrDefault("leaderboard", List.of());
        return board;
    }

    public Map<String, Object> getBadge(String agentId) throws AAIPException {
        return get("agents/" + agentId + "/badge");
    }

    // ─────────────────────────────────────────────
    // Payments
    // ─────────────────────────────────────────────

    public Map<String, Object> getQuote(String agentId) throws AAIPException {
        return post("payments/quote", Map.of("agent_id", agentId));
    }

    public Map<String, Object> verifyPayment(String txHash, String chain) throws AAIPException {
        return post("payments/verify", Map.of("tx_hash", txHash, "chain", chain));
    }

    public Map<String, Object> executePaidTask(String agentId, String task, String txHash) throws AAIPException {
        return post("tasks/execute-paid", Map.of(
            "agent_id", agentId,
            "task", task,
            "payment_tx_hash", txHash
        ));
    }

    // ─────────────────────────────────────────────
    // Utility
    // ─────────────────────────────────────────────

    public Map<String, Object> health() throws AAIPException {
        return get("health");
    }

    public Map<String, Object> networkStats() throws AAIPException {
        return get("stats/network");
    }

    // ─────────────────────────────────────────────
    // Models
    // ─────────────────────────────────────────────

    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class AgentManifest {
        @JsonProperty("agent_name")   public final String agentName;
        @JsonProperty("owner")        public final String owner;
        @JsonProperty("endpoint")     public final String endpoint;
        @JsonProperty("description")  public final String description;
        @JsonProperty("version")      public final String version;
        @JsonProperty("capabilities") public final List<String> capabilities;
        @JsonProperty("domains")      public final List<String> domains;
        @JsonProperty("tools")        public final List<String> tools;
        @JsonProperty("tags")         public final List<String> tags;
        @JsonProperty("framework")    public final String framework;

        private AgentManifest(Builder b) {
            this.agentName    = b.agentName;
            this.owner        = b.owner;
            this.endpoint     = b.endpoint;
            this.description  = b.description;
            this.version      = b.version;
            this.capabilities = b.capabilities;
            this.domains      = b.domains;
            this.tools        = b.tools;
            this.tags         = b.tags;
            this.framework    = b.framework;
        }

        public static class Builder {
            private String agentName, owner, endpoint;
            private String description = "", version = "1.0.0", framework;
            private List<String> capabilities = new ArrayList<>();
            private List<String> domains = new ArrayList<>();
            private List<String> tools = new ArrayList<>();
            private List<String> tags = new ArrayList<>();

            public Builder agentName(String v)        { agentName = v; return this; }
            public Builder owner(String v)            { owner = v; return this; }
            public Builder endpoint(String v)         { endpoint = v; return this; }
            public Builder description(String v)      { description = v; return this; }
            public Builder version(String v)          { version = v; return this; }
            public Builder framework(String v)        { framework = v; return this; }
            public Builder capabilities(List<String> v) { capabilities = v; return this; }
            public Builder domains(List<String> v)    { domains = v; return this; }
            public Builder tools(List<String> v)      { tools = v; return this; }
            public Builder tags(List<String> v)       { tags = v; return this; }
            public AgentManifest build()              { return new AgentManifest(this); }
        }
    }

    // ─────────────────────────────────────────────
    // PoE Trace Builder
    // ─────────────────────────────────────────────

    public static class PoETrace {
        private final String taskId;
        private final String agentId;
        private final String taskDescription;
        private final long startedAtMs;
        private long completedAtMs;
        private final List<Map<String, Object>> steps = new ArrayList<>();
        private final List<Map<String, Object>> toolCalls = new ArrayList<>();
        private final List<Map<String, Object>> reasoningSteps = new ArrayList<>();
        private int totalToolCalls = 0, totalLLMCalls = 0, totalAPICalls = 0;
        private String poeHash;

        public PoETrace(String taskId, String agentId, String taskDescription) {
            this.taskId = taskId;
            this.agentId = agentId;
            this.taskDescription = taskDescription;
            this.startedAtMs = System.currentTimeMillis();
        }

        public PoETrace tool(String name, long latencyMs) {
            Map<String, Object> step = new LinkedHashMap<>();
            step.put("step_type", "tool_call");
            step.put("name", name);
            step.put("timestamp_ms", System.currentTimeMillis());
            step.put("latency_ms", latencyMs);
            step.put("status", "success");
            steps.add(step);
            toolCalls.add(Map.of("tool", name, "latency_ms", latencyMs));
            totalToolCalls++;
            return this;
        }

        public PoETrace reason(String thought) {
            String hash = sha256Short(thought);
            Map<String, Object> step = new LinkedHashMap<>();
            step.put("step_type", "reasoning");
            step.put("name", "reasoning");
            step.put("timestamp_ms", System.currentTimeMillis());
            step.put("output_hash", hash);
            step.put("status", "success");
            steps.add(step);
            reasoningSteps.add(Map.of("hash", hash));
            return this;
        }

        public PoETrace llmCall(String model, int tokensIn, int tokensOut, long latencyMs) {
            Map<String, Object> step = new LinkedHashMap<>();
            step.put("step_type", "llm_call");
            step.put("name", model);
            step.put("timestamp_ms", System.currentTimeMillis());
            step.put("latency_ms", latencyMs);
            step.put("metadata", Map.of("tokens_in", tokensIn, "tokens_out", tokensOut));
            step.put("status", "success");
            steps.add(step);
            totalLLMCalls++;
            return this;
        }

        public void finish() {
            completedAtMs = System.currentTimeMillis();
            poeHash = computeHash();
        }

        public String computeHash() {
            StringBuilder sb = new StringBuilder(taskId).append(":").append(agentId).append(":").append(startedAtMs);
            for (Map<String, Object> s : steps) {
                sb.append(":").append(s.get("step_type")).append(":").append(s.get("name"))
                  .append(":").append(s.get("timestamp_ms")).append(":").append(s.get("status"));
            }
            return sha256(sb.toString());
        }

        public Map<String, Object> toMap() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("task_id", taskId);
            m.put("agent_id", agentId);
            m.put("task_description", taskDescription);
            m.put("started_at_ms", startedAtMs);
            m.put("completed_at_ms", completedAtMs > 0 ? completedAtMs : System.currentTimeMillis());
            m.put("steps", steps);
            m.put("total_tool_calls", totalToolCalls);
            m.put("total_llm_calls", totalLLMCalls);
            m.put("total_api_calls", totalAPICalls);
            m.put("tool_calls", toolCalls);
            m.put("reasoning_steps", reasoningSteps);
            m.put("token_usage", Map.of());
            m.put("poe_hash", poeHash != null ? poeHash : computeHash());
            return m;
        }

        private static String sha256(String input) {
            try {
                MessageDigest md = MessageDigest.getInstance("SHA-256");
                byte[] bytes = md.digest(input.getBytes(StandardCharsets.UTF_8));
                StringBuilder hex = new StringBuilder();
                for (byte b : bytes) hex.append(String.format("%02x", b));
                return hex.toString();
            } catch (Exception e) {
                return "error";
            }
        }

        private static String sha256Short(String input) {
            return sha256(input).substring(0, 16);
        }
    }

    // ─────────────────────────────────────────────
    // Exceptions
    // ─────────────────────────────────────────────

    public static class AAIPException extends Exception {
        public AAIPException(String message) { super(message); }
        public AAIPException(String message, Throwable cause) { super(message, cause); }
    }

    public static class AAIPAuthException extends AAIPException {
        public AAIPAuthException(String message) { super(message); }
    }

    public static class AAIPNotFoundException extends AAIPException {
        public AAIPNotFoundException(String message) { super(message); }
    }

    public static class AAIPValidationException extends AAIPException {
        public AAIPValidationException(String message) { super(message); }
    }

    public static class AAIPRateLimitException extends AAIPException {
        public AAIPRateLimitException(String message) { super(message); }
    }
}
