// Package aaip provides the Go SDK for the Autonomous Agent Infrastructure Protocol.
// https://vuneum.com
//
// Usage:
//
//	client := aaip.NewClient(aaip.Options{APIKey: "your-key"})
//
//	manifest := aaip.AgentManifest{
//	    AgentName:    "MyAgent",
//	    Owner:        "YourCo",
//	    Endpoint:     "https://api.yourco.com/agent",
//	    Capabilities: []string{"code_analysis", "translation"},
//	    Framework:    "custom",
//	}
//	result, err := client.Register(context.Background(), manifest)
package aaip

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"time"
)

const (
	DefaultBaseURL = "https://api.vuneum.com"
	SDKVersion     = "1.0.0"
)

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

// AgentManifest describes your agent for the AAIP registry.
// AAIP does not create your agent — you register one you already built.
type AgentManifest struct {
	AgentName    string                 `json:"agent_name"`
	Owner        string                 `json:"owner"`
	Endpoint     string                 `json:"endpoint"`
	Description  string                 `json:"description,omitempty"`
	Version      string                 `json:"version,omitempty"`
	Capabilities []string               `json:"capabilities,omitempty"`
	Domains      []string               `json:"domains,omitempty"`
	Tools        []string               `json:"tools,omitempty"`
	Tags         []string               `json:"tags,omitempty"`
	Framework    string                 `json:"framework,omitempty"`
	PublicKey    string                 `json:"public_key,omitempty"`
	Metadata     map[string]interface{} `json:"metadata,omitempty"`
}

// PoETraceStep is a single verifiable step in agent execution.
type PoETraceStep struct {
	StepType    string                 `json:"step_type"`
	Name        string                 `json:"name"`
	TimestampMs int64                  `json:"timestamp_ms"`
	InputHash   string                 `json:"input_hash,omitempty"`
	OutputHash  string                 `json:"output_hash,omitempty"`
	LatencyMs   int64                  `json:"latency_ms,omitempty"`
	Status      string                 `json:"status"`
	Metadata    map[string]interface{} `json:"metadata,omitempty"`
}

// PoETrace is a Proof-of-Execution trace for an agent task.
type PoETrace struct {
	TaskID          string                   `json:"task_id"`
	AgentID         string                   `json:"agent_id"`
	TaskDescription string                   `json:"task_description"`
	StartedAtMs     int64                    `json:"started_at_ms"`
	CompletedAtMs   int64                    `json:"completed_at_ms"`
	Steps           []PoETraceStep           `json:"steps"`
	TotalToolCalls  int                      `json:"total_tool_calls"`
	TotalLLMCalls   int                      `json:"total_llm_calls"`
	TotalAPICalls   int                      `json:"total_api_calls"`
	ToolCalls       []map[string]interface{} `json:"tool_calls"`
	ReasoningSteps  []map[string]interface{} `json:"reasoning_steps"`
	TokenUsage      map[string]int           `json:"token_usage"`
	PoEHash         string                   `json:"poe_hash,omitempty"`
}

// ComputeHash computes the SHA-256 fingerprint of the trace.
func (t *PoETrace) ComputeHash() string {
	data := fmt.Sprintf("%s:%s:%d", t.TaskID, t.AgentID, t.StartedAtMs)
	for _, s := range t.Steps {
		data += fmt.Sprintf(":%s:%s:%d:%s", s.StepType, s.Name, s.TimestampMs, s.Status)
	}
	h := sha256.Sum256([]byte(data))
	return fmt.Sprintf("%x", h)
}

// EvaluationResponse contains the multi-model jury evaluation result.
type EvaluationResponse struct {
	EvaluationID          string             `json:"evaluation_id"`
	AgentID               string             `json:"agent_id"`
	TaskDomain            string             `json:"task_domain"`
	JudgeScores           map[string]float64 `json:"judge_scores"`
	FinalScore            float64            `json:"final_score"`
	ScoreVariance         float64            `json:"score_variance"`
	AgreementLevel        string             `json:"agreement_level"`
	ConfidenceIntervalLow float64            `json:"confidence_interval_low"`
	PoEVerified           bool               `json:"poe_verified"`
	PoEHash               string             `json:"poe_hash,omitempty"`
	Timestamp             string             `json:"timestamp,omitempty"`
}

// DiscoveryResult represents an agent found in the AAIP registry.
type DiscoveryResult struct {
	AAIPAgentID     string   `json:"aaip_agent_id"`
	AgentName       string   `json:"agent_name"`
	Owner           string   `json:"owner"`
	Description     string   `json:"description,omitempty"`
	Endpoint        string   `json:"endpoint,omitempty"`
	Capabilities    []string `json:"capabilities,omitempty"`
	Domains         []string `json:"domains,omitempty"`
	Framework       string   `json:"framework,omitempty"`
	ReputationScore float64  `json:"reputation_score,omitempty"`
}

// LeaderboardEntry is a ranked agent on the global leaderboard.
type LeaderboardEntry struct {
	Rank            int     `json:"rank"`
	AAIPAgentID     string  `json:"aaip_agent_id"`
	AgentName       string  `json:"agent_name"`
	CompanyName     string  `json:"company_name"`
	Domain          string  `json:"domain"`
	AverageScore    float64 `json:"average_score"`
	EvaluationCount int     `json:"evaluation_count"`
}

// ─────────────────────────────────────────────
// Client
// ─────────────────────────────────────────────

// Options configures the AAIP client.
type Options struct {
	APIKey  string
	BaseURL string
	Timeout time.Duration
}

// Client is the AAIP API client.
type Client struct {
	apiKey  string
	baseURL string
	http    *http.Client
}

// NewClient creates a new AAIP client.
func NewClient(opts Options) *Client {
	apiKey := opts.APIKey
	if apiKey == "" {
		apiKey = os.Getenv("AAIP_API_KEY")
	}
	baseURL := opts.BaseURL
	if baseURL == "" {
		baseURL = os.Getenv("AAIP_BASE_URL")
	}
	if baseURL == "" {
		baseURL = DefaultBaseURL
	}
	timeout := opts.Timeout
	if timeout == 0 {
		timeout = 30 * time.Second
	}
	return &Client{
		apiKey:  apiKey,
		baseURL: baseURL,
		http:    &http.Client{Timeout: timeout},
	}
}

func (c *Client) headers() map[string]string {
	h := map[string]string{
		"Content-Type": "application/json",
		"User-Agent":   "aaip-go-sdk/" + SDKVersion,
		"X-AAIP-Version": "1",
	}
	if c.apiKey != "" {
		h["Authorization"] = "Bearer " + c.apiKey
	}
	return h
}

func (c *Client) do(ctx context.Context, method, path string, body interface{}, params map[string]string) ([]byte, error) {
	u := c.baseURL + "/" + path

	if len(params) > 0 {
		q := url.Values{}
		for k, v := range params {
			q.Set(k, v)
		}
		u += "?" + q.Encode()
	}

	var bodyReader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("marshal body: %w", err)
		}
		bodyReader = bytes.NewReader(b)
	}

	req, err := http.NewRequestWithContext(ctx, method, u, bodyReader)
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	for k, v := range c.headers() {
		req.Header.Set(k, v)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http request: %w", err)
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}

	if resp.StatusCode == 401 {
		return nil, fmt.Errorf("authentication error: invalid or missing API key")
	}
	if resp.StatusCode == 404 {
		return nil, fmt.Errorf("not found: %s", u)
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("API error %d: %s", resp.StatusCode, string(data))
	}

	return data, nil
}

// ── Identity & Registration ──────────────

// Register registers your agent with the AAIP network.
func (c *Client) Register(ctx context.Context, manifest AgentManifest) (map[string]interface{}, error) {
	data, err := c.do(ctx, "POST", "discovery/register", map[string]interface{}{"manifest": manifest}, nil)
	if err != nil {
		return nil, err
	}
	var result map[string]interface{}
	return result, json.Unmarshal(data, &result)
}

// GetAgent retrieves an agent's full profile.
func (c *Client) GetAgent(ctx context.Context, agentID string) (map[string]interface{}, error) {
	data, err := c.do(ctx, "GET", "agents/"+agentID, nil, nil)
	if err != nil {
		return nil, err
	}
	var result map[string]interface{}
	return result, json.Unmarshal(data, &result)
}

// ── Discovery ────────────────────────────

// DiscoverOptions filters agent discovery.
type DiscoverOptions struct {
	Capability    string
	Domain        string
	Tag           string
	MinReputation float64
	Limit         int
}

// Discover searches for agents by capability, domain, or tag.
func (c *Client) Discover(ctx context.Context, opts DiscoverOptions) ([]DiscoveryResult, error) {
	params := map[string]string{"limit": strconv.Itoa(max(opts.Limit, 20))}
	if opts.Capability != "" {
		params["capability"] = opts.Capability
	}
	if opts.Domain != "" {
		params["domain"] = opts.Domain
	}
	if opts.Tag != "" {
		params["tag"] = opts.Tag
	}

	data, err := c.do(ctx, "GET", "discovery/agents", nil, params)
	if err != nil {
		return nil, err
	}
	var resp struct {
		Agents []DiscoveryResult `json:"agents"`
	}
	return resp.Agents, json.Unmarshal(data, &resp)
}

// ── Evaluation ───────────────────────────

// EvaluateOptions configures an evaluation request.
type EvaluateOptions struct {
	Domain              string
	Trace               *PoETrace
	JudgeIDs            []string
	BenchmarkDatasetID  string
	AsyncMode           bool
}

// Evaluate submits agent output for multi-model jury evaluation.
func (c *Client) Evaluate(ctx context.Context, agentID, taskDesc, output string, opts EvaluateOptions) (*EvaluationResponse, error) {
	body := map[string]interface{}{
		"agent_id":         agentID,
		"task_domain":      firstNonEmpty(opts.Domain, "general"),
		"task_description": taskDesc,
		"agent_output":     output,
		"async_mode":       opts.AsyncMode,
	}
	if opts.Trace != nil {
		opts.Trace.PoEHash = opts.Trace.ComputeHash()
		body["trace"] = opts.Trace
	}
	if len(opts.JudgeIDs) > 0 {
		body["selected_judge_ids"] = opts.JudgeIDs
	}

	endpoint := "evaluate"
	if opts.AsyncMode {
		endpoint = "jobs/evaluate"
	}

	data, err := c.do(ctx, "POST", endpoint, body, nil)
	if err != nil {
		return nil, err
	}
	var result EvaluationResponse
	return &result, json.Unmarshal(data, &result)
}

// ── Proof of Execution ───────────────────

// SubmitTrace submits a PoE trace for an agent task.
func (c *Client) SubmitTrace(ctx context.Context, agentID string, trace *PoETrace) (map[string]interface{}, error) {
	trace.PoEHash = trace.ComputeHash()
	body := map[string]interface{}{
		"agent_id": agentID,
		"trace":    trace,
		"poe_hash": trace.PoEHash,
	}
	data, err := c.do(ctx, "POST", "traces/submit", body, nil)
	if err != nil {
		return nil, err
	}
	var result map[string]interface{}
	return result, json.Unmarshal(data, &result)
}

// ── Reputation & Leaderboard ─────────────

// GetReputation retrieves reputation timeline for an agent.
func (c *Client) GetReputation(ctx context.Context, agentID string, days int) (map[string]interface{}, error) {
	params := map[string]string{"days": strconv.Itoa(days)}
	data, err := c.do(ctx, "GET", "agents/"+agentID+"/reputation", nil, params)
	if err != nil {
		return nil, err
	}
	var result map[string]interface{}
	return result, json.Unmarshal(data, &result)
}

// GetLeaderboard retrieves the global agent leaderboard.
func (c *Client) GetLeaderboard(ctx context.Context, domain string, limit int) ([]LeaderboardEntry, error) {
	params := map[string]string{"limit": strconv.Itoa(max(limit, 20))}
	if domain != "" {
		params["domain"] = domain
	}
	data, err := c.do(ctx, "GET", "leaderboard", nil, params)
	if err != nil {
		return nil, err
	}
	var resp struct {
		Leaderboard []LeaderboardEntry `json:"leaderboard"`
	}
	return resp.Leaderboard, json.Unmarshal(data, &resp)
}

// Health checks the AAIP API health.
func (c *Client) Health(ctx context.Context) (map[string]interface{}, error) {
	data, err := c.do(ctx, "GET", "health", nil, nil)
	if err != nil {
		return nil, err
	}
	var result map[string]interface{}
	return result, json.Unmarshal(data, &result)
}

// ─────────────────────────────────────────────
// PoE Builder
// ─────────────────────────────────────────────

// NewPoETrace creates a new Proof-of-Execution trace builder.
func NewPoETrace(taskID, agentID, taskDescription string) *PoETrace {
	return &PoETrace{
		TaskID:          taskID,
		AgentID:         agentID,
		TaskDescription: taskDescription,
		StartedAtMs:     time.Now().UnixMilli(),
		Steps:           []PoETraceStep{},
		ToolCalls:       []map[string]interface{}{},
		ReasoningSteps:  []map[string]interface{}{},
		TokenUsage:      map[string]int{},
	}
}

// AddTool records a tool call in the trace.
func (t *PoETrace) AddTool(name string, latencyMs int64) {
	t.Steps = append(t.Steps, PoETraceStep{
		StepType:    "tool_call",
		Name:        name,
		TimestampMs: time.Now().UnixMilli(),
		LatencyMs:   latencyMs,
		Status:      "success",
	})
	t.TotalToolCalls++
	t.ToolCalls = append(t.ToolCalls, map[string]interface{}{"tool": name, "latency_ms": latencyMs})
}

// AddReason records a reasoning step (stored as hash).
func (t *PoETrace) AddReason(thought string) {
	h := sha256.Sum256([]byte(thought))
	hash := fmt.Sprintf("%x", h)[:16]
	t.Steps = append(t.Steps, PoETraceStep{
		StepType:    "reasoning",
		Name:        "reasoning",
		TimestampMs: time.Now().UnixMilli(),
		OutputHash:  hash,
		Status:      "success",
	})
	t.ReasoningSteps = append(t.ReasoningSteps, map[string]interface{}{"hash": hash})
}

// Finish marks the trace as complete.
func (t *PoETrace) Finish() {
	t.CompletedAtMs = time.Now().UnixMilli()
	t.PoEHash = t.ComputeHash()
}

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
