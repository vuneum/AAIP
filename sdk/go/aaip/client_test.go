package aaip_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/aaip-protocol/aaip/sdk/go/aaip"
)

// newMockServer returns a test server that responds to every POST with
// the given JSON body and status code.
func newMockServer(t *testing.T, status int, body any) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		if err := json.NewEncoder(w).Encode(body); err != nil {
			t.Errorf("mock server encode: %v", err)
		}
	}))
}

func TestNewClient_Defaults(t *testing.T) {
	c := aaip.NewClient(aaip.Options{})
	if c == nil {
		t.Fatal("NewClient returned nil")
	}
}

func TestNewClient_APIKeyOption(t *testing.T) {
	c := aaip.NewClient(aaip.Options{APIKey: "test-key-abc"})
	if c == nil {
		t.Fatal("NewClient returned nil")
	}
}

func TestRegister_Success(t *testing.T) {
	srv := newMockServer(t, 200, map[string]any{
		"agent_id": "test-agent-001",
		"status":   "registered",
	})
	defer srv.Close()

	c := aaip.NewClient(aaip.Options{BaseURL: srv.URL})
	manifest := aaip.AgentManifest{
		AgentName:    "TestAgent",
		Owner:        "TestOwner",
		Endpoint:     "https://example.com/agent",
		Capabilities: []string{"code_analysis"},
		Framework:    "custom",
	}

	result, err := c.Register(context.Background(), manifest)
	if err != nil {
		t.Fatalf("Register returned error: %v", err)
	}
	if result == nil {
		t.Fatal("Register returned nil result")
	}
}

func TestRegister_ServerError(t *testing.T) {
	srv := newMockServer(t, 500, map[string]any{"detail": "internal error"})
	defer srv.Close()

	c := aaip.NewClient(aaip.Options{BaseURL: srv.URL})
	_, err := c.Register(context.Background(), aaip.AgentManifest{
		AgentName: "ErrorAgent",
	})
	if err == nil {
		t.Fatal("expected error from 500 response, got nil")
	}
}

func TestRegister_AuthError(t *testing.T) {
	srv := newMockServer(t, 401, map[string]any{"detail": "unauthorized"})
	defer srv.Close()

	c := aaip.NewClient(aaip.Options{BaseURL: srv.URL, APIKey: "bad-key"})
	_, err := c.Register(context.Background(), aaip.AgentManifest{
		AgentName: "AuthAgent",
	})
	if err == nil {
		t.Fatal("expected auth error, got nil")
	}
}

func TestGetReputation_NotFound(t *testing.T) {
	srv := newMockServer(t, 404, map[string]any{"detail": "agent not found"})
	defer srv.Close()

	c := aaip.NewClient(aaip.Options{BaseURL: srv.URL})
	_, err := c.GetReputation(context.Background(), "nonexistent-agent")
	if err == nil {
		t.Fatal("expected not-found error, got nil")
	}
}

func TestDiscover_Success(t *testing.T) {
	srv := newMockServer(t, 200, map[string]any{
		"agents": []map[string]any{
			{"agent_id": "a1", "capabilities": []string{"nlp"}},
		},
		"total": 1,
	})
	defer srv.Close()

	c := aaip.NewClient(aaip.Options{BaseURL: srv.URL})
	result, err := c.Discover(context.Background(), aaip.DiscoveryQuery{
		Capability: "nlp",
	})
	if err != nil {
		t.Fatalf("Discover returned error: %v", err)
	}
	if result == nil {
		t.Fatal("Discover returned nil result")
	}
}