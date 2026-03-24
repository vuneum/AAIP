/**
 * AAIP TypeScript/JavaScript SDK
 * Autonomous Agent Infrastructure Protocol
 * https://vuneum.com
 *
 * Works in Node.js, Next.js, Deno, and modern browsers.
 */

// ─────────────────────────────────────────────
// Types & Models
// ─────────────────────────────────────────────

export interface AgentManifest {
  agent_name: string;
  owner: string;
  endpoint: string;
  description?: string;
  version?: string;
  capabilities?: string[];
  domains?: string[];
  tools?: string[];
  tags?: string[];
  framework?: "langchain" | "crewai" | "openai_agents" | "autogpt" | "custom" | string;
  framework_version?: string;
  payment?: PaymentConfig;
  public_key?: string;
  metadata?: Record<string, unknown>;
}

export interface PaymentConfig {
  enabled: boolean;
  integration_mode: "core" | "full";
  model: "pay_per_request" | "subscription";
  accepted_tokens: string[];
  chains: string[];
  wallets: Array<{ chain: string; address: string }>;
  pricing?: {
    default_request?: { amount: string; currency: string };
  };
}

export interface PoETraceStep {
  step_type: "tool_call" | "llm_call" | "api_call" | "reasoning" | "retrieval";
  name: string;
  timestamp_ms: number;
  input_hash?: string;
  output_hash?: string;
  latency_ms?: number;
  status: "success" | "error" | "skipped";
  metadata?: Record<string, unknown>;
}

export interface PoETrace {
  task_id: string;
  agent_id: string;
  task_description: string;
  started_at_ms: number;
  completed_at_ms: number;
  steps: PoETraceStep[];
  total_tool_calls: number;
  total_llm_calls: number;
  total_api_calls: number;
  total_tokens?: number;
  total_latency_ms?: number;
  tool_calls: Record<string, unknown>[];
  reasoning_steps: Record<string, unknown>[];
  token_usage: Record<string, number>;
  metadata?: Record<string, unknown>;
  poe_hash?: string;
}

export interface EvaluationResponse {
  evaluation_id: string;
  agent_id: string;
  task_domain: string;
  judge_scores: Record<string, number>;
  final_score: number;
  score_variance: number;
  agreement_level: "high" | "moderate" | "low" | "insufficient_data";
  confidence_interval?: { low: number; high: number };
  benchmark_score?: number;
  historical_reliability?: number;
  poe_verified: boolean;
  poe_hash?: string;
  timestamp?: string;
}

export interface DiscoveryResult {
  aaip_agent_id: string;
  agent_name: string;
  owner: string;
  description?: string;
  endpoint?: string;
  capabilities?: string[];
  domains?: string[];
  tags?: string[];
  framework?: string;
  reputation_score?: number;
  evaluation_count?: number;
}

export interface ReputationSummary {
  current_reputation: number;
  trend_delta: number;
  evaluations: number;
  window_days: number;
}

export interface LeaderboardEntry {
  rank: number;
  aaip_agent_id: string;
  agent_name: string;
  company_name: string;
  domain: string;
  average_score: number;
  evaluation_count: number;
}

export interface PaymentQuote {
  agent_id: string;
  amount: string;
  currency: string;
  chain: string;
  wallet_address: string;
  expires_at: string;
  quote_id: string;
}

export class AAIPError extends Error {
  constructor(message: string, public statusCode?: number) {
    super(message);
    this.name = "AAIPError";
  }
}
export class AuthError extends AAIPError { constructor(msg: string) { super(msg, 401); this.name = "AuthError"; } }
export class NotFoundError extends AAIPError { constructor(msg: string) { super(msg, 404); this.name = "NotFoundError"; } }
export class ValidationError extends AAIPError { constructor(msg: string) { super(msg, 422); this.name = "ValidationError"; } }


// ─────────────────────────────────────────────
// PoE Builder
// ─────────────────────────────────────────────

import * as crypto from "crypto";

export class ProofOfExecution {
  public trace: PoETrace;

  constructor(taskId: string, agentId: string, taskDescription = "") {
    this.trace = {
      task_id: taskId,
      agent_id: agentId,
      task_description: taskDescription,
      started_at_ms: Date.now(),
      completed_at_ms: 0,
      steps: [],
      total_tool_calls: 0,
      total_llm_calls: 0,
      total_api_calls: 0,
      tool_calls: [],
      reasoning_steps: [],
      token_usage: {},
    };
  }

  start(): this {
    this.trace.started_at_ms = Date.now();
    return this;
  }

  finish(): this {
    this.trace.completed_at_ms = Date.now();
    return this;
  }

  tool(name: string, inputs: unknown = {}, output: unknown = {}, latencyMs = 0): this {
    const inputHash = this._hash(JSON.stringify(inputs)).slice(0, 16);
    const outputHash = this._hash(JSON.stringify(output)).slice(0, 16);

    this.trace.steps.push({
      step_type: "tool_call",
      name,
      timestamp_ms: Date.now(),
      input_hash: inputHash,
      output_hash: outputHash,
      latency_ms: latencyMs,
      status: "success",
    });

    this.trace.tool_calls.push({ tool: name, input_hash: inputHash, output_hash: outputHash, latency_ms: latencyMs });
    this.trace.total_tool_calls++;
    return this;
  }

  reason(thought: string): this {
    const hash = this._hash(thought).slice(0, 16);
    this.trace.steps.push({
      step_type: "reasoning",
      name: "reasoning",
      timestamp_ms: Date.now(),
      output_hash: hash,
      status: "success",
    });
    this.trace.reasoning_steps.push({ hash });
    return this;
  }

  llmCall(model: string, tokensIn = 0, tokensOut = 0, latencyMs = 0): this {
    this.trace.steps.push({
      step_type: "llm_call",
      name: model,
      timestamp_ms: Date.now(),
      latency_ms: latencyMs,
      status: "success",
      metadata: { tokens_in: tokensIn, tokens_out: tokensOut },
    });
    this.trace.total_llm_calls++;
    this.trace.token_usage.total_tokens = (this.trace.token_usage.total_tokens ?? 0) + tokensIn + tokensOut;
    return this;
  }

  apiCall(endpoint: string, status: "success" | "error" = "success", latencyMs = 0): this {
    this.trace.steps.push({
      step_type: "api_call",
      name: endpoint,
      timestamp_ms: Date.now(),
      latency_ms: latencyMs,
      status,
    });
    this.trace.total_api_calls++;
    return this;
  }

  computeHash(): string {
    const parts = [this.trace.task_id, this.trace.agent_id, this.trace.started_at_ms.toString()];
    for (const s of this.trace.steps) {
      parts.push(`${s.step_type}:${s.name}:${s.timestamp_ms}:${s.status}`);
    }
    return this._hash(parts.join(":"));
  }

  toDict(): PoETrace & { poe_hash: string } {
    return { ...this.trace, completed_at_ms: this.trace.completed_at_ms || Date.now(), poe_hash: this.computeHash() };
  }

  private _hash(data: string): string {
    if (typeof crypto !== "undefined" && crypto.createHash) {
      return crypto.createHash("sha256").update(data).digest("hex");
    }
    // Browser fallback: simple hash
    let h = 0;
    for (let i = 0; i < data.length; i++) {
      h = Math.imul(31, h) + data.charCodeAt(i) | 0;
    }
    return Math.abs(h).toString(16).padStart(8, "0").repeat(8);
  }
}


// ─────────────────────────────────────────────
// Main Client
// ─────────────────────────────────────────────

export interface AAIPClientOptions {
  apiKey?: string;
  baseUrl?: string;
  timeout?: number;
}

export interface EvaluateOptions {
  domain?: string;
  trace?: ProofOfExecution | PoETrace;
  judgeIds?: string[];
  benchmarkDatasetId?: string;
  asyncMode?: boolean;
}

export interface DiscoverOptions {
  capability?: string;
  domain?: string;
  tag?: string;
  minReputation?: number;
  limit?: number;
}

export class AAIPClient {
  private apiKey: string;
  private baseUrl: string;
  private timeout: number;

  constructor(options: AAIPClientOptions = {}) {
    this.apiKey = options.apiKey ?? (typeof process !== "undefined" ? process.env.AAIP_API_KEY ?? "" : "");
    this.baseUrl = (options.baseUrl ?? (typeof process !== "undefined" ? process.env.AAIP_BASE_URL ?? "https://api.vuneum.com" : "https://api.vuneum.com")).replace(/\/$/, "");
    this.timeout = options.timeout ?? 30000;
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = {
      "Content-Type": "application/json",
      "User-Agent": "aaip-ts-sdk/1.0.0",
      "X-AAIP-Version": "1",
    };
    if (this.apiKey) h["Authorization"] = `Bearer ${this.apiKey}`;
    return h;
  }

  private url(path: string): string {
    return `${this.baseUrl}/${path.replace(/^\//, "")}`;
  }

  private async request<T>(method: string, path: string, body?: unknown, params?: Record<string, string>): Promise<T> {
    let url = this.url(path);
    if (params) {
      const qs = new URLSearchParams(params).toString();
      if (qs) url += `?${qs}`;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const res = await fetch(url, {
        method,
        headers: this.headers(),
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });

      clearTimeout(timer);

      if (res.status === 401) throw new AuthError("Invalid or missing API key");
      if (res.status === 404) throw new NotFoundError(`Not found: ${url}`);
      if (res.status === 422) throw new ValidationError(await res.text());
      if (!res.ok) throw new AAIPError(`API error ${res.status}`, res.status);

      return res.json() as Promise<T>;
    } catch (e) {
      clearTimeout(timer);
      throw e;
    }
  }

  // ── Identity & Registration ──────────────

  async register(manifest: AgentManifest): Promise<Record<string, unknown>> {
    return this.request("POST", "/discovery/register", { manifest });
  }

  async getAgent(agentId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/agents/${agentId}`);
  }

  // ── Discovery ────────────────────────────

  async discover(options: DiscoverOptions = {}): Promise<DiscoveryResult[]> {
    const params: Record<string, string> = { limit: String(options.limit ?? 20) };
    if (options.capability) params.capability = options.capability;
    if (options.domain) params.domain = options.domain;
    if (options.tag) params.tag = options.tag;
    if (options.minReputation != null) params.min_reputation = String(options.minReputation);

    const data = await this.request<{ agents: DiscoveryResult[] }>("GET", "/discovery/agents", undefined, params);
    return data.agents ?? [];
  }

  async crawl(baseUrl: string): Promise<Record<string, unknown>> {
    return this.request("POST", "/discovery/crawl", { base_url: baseUrl });
  }

  // ── Evaluation & AI Jury ─────────────────

  async evaluate(
    agentId: string,
    taskDescription: string,
    agentOutput: string,
    options: EvaluateOptions = {}
  ): Promise<EvaluationResponse> {
    const body: Record<string, unknown> = {
      agent_id: agentId,
      task_domain: options.domain ?? "general",
      task_description: taskDescription,
      agent_output: agentOutput,
      async_mode: options.asyncMode ?? false,
    };

    if (options.trace) {
      const t = options.trace instanceof ProofOfExecution ? options.trace.toDict() : options.trace;
      body.trace = t;
    }
    if (options.judgeIds?.length) body.selected_judge_ids = options.judgeIds;
    if (options.benchmarkDatasetId) body.benchmark_dataset_id = options.benchmarkDatasetId;

    const endpoint = options.asyncMode ? "/jobs/evaluate" : "/evaluate";
    return this.request<EvaluationResponse>("POST", endpoint, body);
  }

  async getJob(jobId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/jobs/${jobId}`);
  }

  async waitForJob(jobId: string, pollInterval = 2000, timeoutMs = 120000): Promise<Record<string, unknown>> {
    const start = Date.now();
    while (true) {
      const job = await this.getJob(jobId);
      if (["completed", "failed"].includes(job.status as string)) return job;
      if (Date.now() - start > timeoutMs) throw new Error(`Job ${jobId} timed out`);
      await new Promise(r => setTimeout(r, pollInterval));
    }
  }

  // ── Proof of Execution ───────────────────

  async submitTrace(agentId: string, trace: ProofOfExecution | PoETrace): Promise<Record<string, unknown>> {
    const t = trace instanceof ProofOfExecution ? trace.toDict() : trace;
    return this.request("POST", "/traces/submit", {
      agent_id: agentId,
      trace: t,
      poe_hash: t.poe_hash,
    });
  }

  async verifyTrace(traceId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/traces/${traceId}/verify`);
  }

  async getTraces(agentId: string, limit = 20): Promise<unknown[]> {
    const data = await this.request<{ traces: unknown[] }>("GET", `/agents/${agentId}/traces`, undefined, { limit: String(limit) });
    return data.traces ?? [];
  }

  // ── Reputation ───────────────────────────

  async getReputation(agentId: string, days = 30): Promise<{ summary: ReputationSummary; timeline: unknown[] }> {
    return this.request("GET", `/agents/${agentId}/reputation`, undefined, { days: String(days) });
  }

  async getLeaderboard(domain?: string, limit = 20): Promise<LeaderboardEntry[]> {
    const params: Record<string, string> = { limit: String(limit) };
    if (domain) params.domain = domain;
    const data = await this.request<{ leaderboard: LeaderboardEntry[] }>("GET", "/leaderboard", undefined, params);
    return data.leaderboard ?? [];
  }

  async getBadge(agentId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/agents/${agentId}/badge`);
  }

  // ── Payments ─────────────────────────────

  async getQuote(agentId: string, task?: string): Promise<PaymentQuote> {
    return this.request<PaymentQuote>("POST", "/payments/quote", { agent_id: agentId, task });
  }

  async verifyPayment(txHash: string, chain = "base"): Promise<Record<string, unknown>> {
    return this.request("POST", "/payments/verify", { tx_hash: txHash, chain });
  }

  async executePaidTask(agentId: string, task: string, paymentTxHash: string, chain = "base"): Promise<Record<string, unknown>> {
    return this.request("POST", "/tasks/execute-paid", { agent_id: agentId, task, payment_tx_hash: paymentTxHash, chain });
  }

  // ── Utility ──────────────────────────────

  async health(): Promise<Record<string, unknown>> {
    return this.request("GET", "/health");
  }

  async networkStats(): Promise<Record<string, unknown>> {
    return this.request("GET", "/stats/network");
  }
}

// Default export for convenience
export default AAIPClient;
