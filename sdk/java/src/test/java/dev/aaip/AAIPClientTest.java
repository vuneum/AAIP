package dev.aaip;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for AAIPClient.
 * These tests verify construction and basic error handling without
 * making real network calls.
 */
class AAIPClientTest {

    // ── Construction ──────────────────────────────────────────────────────────

    @Test
    void testClientConstructsWithApiKey() {
        AAIPClient client = new AAIPClient("test-api-key");
        assertNotNull(client, "Client should not be null");
    }

    @Test
    void testClientConstructsWithApiKeyAndBaseUrl() {
        AAIPClient client = new AAIPClient("test-api-key", "https://custom.api.example.com");
        assertNotNull(client, "Client with custom base URL should not be null");
    }

    @Test
    void testClientConstructsWithEmptyKey() {
        // Empty key is allowed at construction time;
        // auth failure happens at the HTTP call level.
        AAIPClient client = new AAIPClient("");
        assertNotNull(client, "Client with empty key should not be null");
    }

    // ── AgentManifest builder ─────────────────────────────────────────────────

    @Test
    void testAgentManifestBuildsCorrectly() {
        AAIPClient.AgentManifest manifest = new AAIPClient.AgentManifest.Builder()
            .agentName("JavaTestAgent")
            .owner("TestOrg")
            .endpoint("https://api.example.com/agent")
            .capability("code_review")
            .capability("summarisation")
            .framework("custom")
            .build();

        assertEquals("JavaTestAgent", manifest.getAgentName());
        assertEquals("TestOrg", manifest.getOwner());
        assertTrue(manifest.getCapabilities().contains("code_review"));
        assertTrue(manifest.getCapabilities().contains("summarisation"));
        assertEquals("custom", manifest.getFramework());
    }

    @Test
    void testAgentManifestRequiresAgentName() {
        assertThrows(IllegalArgumentException.class, () ->
            new AAIPClient.AgentManifest.Builder()
                .owner("Owner")
                .endpoint("https://example.com")
                .build(),
            "Building a manifest without agentName should throw"
        );
    }

    @Test
    void testAgentManifestRequiresEndpoint() {
        assertThrows(IllegalArgumentException.class, () ->
            new AAIPClient.AgentManifest.Builder()
                .agentName("Agent")
                .owner("Owner")
                .build(),
            "Building a manifest without endpoint should throw"
        );
    }

    // ── DiscoveryQuery ────────────────────────────────────────────────────────

    @Test
    void testDiscoveryQueryBuildsCorrectly() {
        AAIPClient.DiscoveryQuery query = new AAIPClient.DiscoveryQuery.Builder()
            .capability("nlp")
            .minReputation(75.0)
            .limit(10)
            .build();

        assertEquals("nlp", query.getCapability());
        assertEquals(75.0, query.getMinReputation(), 0.001);
        assertEquals(10, query.getLimit());
    }
}
