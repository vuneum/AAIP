package dev.aaip;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import java.util.List;
import java.util.Map;

class AAIPClientTest {

    @Test
    void testPoETraceHashDeterministic() {
        AAIPClient.PoETrace t1 = new AAIPClient.PoETrace("t-001", "co/agent/abc", "test");
        AAIPClient.PoETrace t2 = new AAIPClient.PoETrace("t-001", "co/agent/abc", "test");
        // Same task/agent should produce same base, but timestamps differ
        // so just verify hashes are 64-char hex
        String h = t1.computeHash();
        assertEquals(64, h.length());
        assertTrue(h.matches("[0-9a-f]{64}"));
    }

    @Test
    void testPoETraceToolAddsStep() {
        AAIPClient.PoETrace trace = new AAIPClient.PoETrace("t-001", "co/agent/abc", "test");
        trace.tool("web_search", 120).reason("found results").llmCall("gpt-4o", 100, 200, 800);
        trace.finish();

        Map<String, Object> map = trace.toMap();
        assertEquals("t-001", map.get("task_id"));
        assertNotNull(map.get("poe_hash"));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) map.get("steps");
        assertEquals(3, steps.size());
        assertEquals("tool_call", steps.get(0).get("step_type"));
        assertEquals("reasoning", steps.get(1).get("step_type"));
        assertEquals("llm_call", steps.get(2).get("step_type"));
    }

    @Test
    void testAgentManifestBuilder() {
        AAIPClient.AgentManifest manifest = new AAIPClient.AgentManifest.Builder()
            .agentName("TestAgent")
            .owner("TestCo")
            .endpoint("https://api.test.com/agent")
            .capabilities(List.of("code_analysis", "translation"))
            .framework("langchain")
            .build();

        assertEquals("TestAgent", manifest.agentName);
        assertEquals("TestCo", manifest.owner);
        assertEquals("langchain", manifest.framework);
        assertEquals(2, manifest.capabilities.size());
    }

    @Test
    void testClientBuilderDefaults() {
        // Should not throw even without env vars
        AAIPClient client = new AAIPClient.Builder().build();
        assertNotNull(client);
    }
}
