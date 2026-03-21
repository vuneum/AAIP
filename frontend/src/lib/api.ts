// AAIP Frontend — API Client
// Autonomous Agent Infrastructure Protocol

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

export interface Agent {
  id: string;
  aaip_agent_id: string;
  company_name: string;
  agent_name: string;
  domain: string;
  version: string;
  created_at: string;
}

export interface AgentStats {
  total_evaluations: number;
  average_score: number;
  domain_breakdown: Record<string, { average_score: number; count: number }>;
}

export interface PoEStats {
  total_traces: number;
  verified_traces: number;
  flagged_traces: number;
  verification_rate: number;
  avg_duration_ms: number;
  avg_steps: number;
}

export interface EvaluationRequest {
  agent_id: string;
  task_domain: string;
  task_description: string;
  agent_output: string;
  async_mode?: boolean;
}

export interface Evaluation {
  evaluation_id: string;
  agent_id: string;
  task_domain: string;
  judge_scores: Record<string, number>;
  final_score: number;
  score_variance: number;
  confidence_interval: { low: number; high: number };
  agreement_level: string;
  grade: string;
  passed: boolean;
  timestamp: string;
}

export interface LeaderboardEntry {
  rank: number;
  aaip_agent_id: string;
  company_name: string;
  agent_name: string;
  domain: string;
  average_score: number;
  evaluation_count: number;
  last_evaluation: string;
}

export interface ReputationTimeline {
  aaip_agent_id: string;
  summary: {
    current_reputation: number;
    peak_reputation: number;
    trend: string;
    evaluation_count: number;
  };
  timeline: Array<{ date: string; score: number; evaluations: number }>;
}

export interface NetworkStats {
  total_agents: number;
  total_evaluations: number;
  average_network_score: number;
  domain_breakdown: Record<string, { count: number; average_score: number }>;
  recent_activity: Array<{
    evaluation_id: string;
    agent_id: string;
    domain: string;
    score: number;
    timestamp: string;
  }>;
}

export interface Badge {
  aaip_agent_id: string;
  agent_name: string;
  score: number;
  grade: string;
  evaluation_count: number;
  badge: {
    label: string;
    message: string;
    color: string;
    shield_url: string;
    markdown: string;
    html: string;
  };
}

export interface PaymentQuote {
  quote_id: string;
  agent_id: string;
  amount: string;
  currency: string;
  chain: string;
  wallet_address: string;
  expires_at: string;
  instructions: string;
}

export interface CAVStatus {
  aaip_agent_id: string;
  total_audits: number;
  passed_audits: number;
  failed_audits: number;
  pass_rate: number;
  last_audit_at: string | null;
  last_result: string | null;
  reputation_adjustments: number;
}

export interface ShadowSession {
  session_id: string;
  aaip_agent_id: string;
  status: string;
  created_at: string;
  expires_at: string;
  report: ShadowReport | null;
}

export interface ShadowReport {
  session_id: string;
  aaip_agent_id: string;
  task_description: string;
  poe_verified: boolean;
  simulated_jury_score: number;
  simulated_grade: string;
  simulated_payment_amount: string;
  cav_audit_triggered: boolean;
  cav_score: number | null;
  reputation_delta: number;
  issues: string[];
  recommendations: string[];
  completed_at: string;
}

// ─────────────────────────────────────────────
// HTTP helper
// ─────────────────────────────────────────────

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const apiKey = typeof window !== 'undefined' ? localStorage.getItem('aaip_api_key') : null;
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

// ─────────────────────────────────────────────
// Agent Registry
// ─────────────────────────────────────────────

export async function registerAgent(data: {
  company_name: string;
  agent_name: string;
  domain: string;
}): Promise<Agent> {
  return fetchJSON<Agent>(`${API_BASE_URL}/agents/register`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function listAgents(): Promise<Agent[]> {
  return fetchJSON<Agent[]>(`${API_BASE_URL}/agents`);
}

export async function getAgent(aaipAgentId: string): Promise<{ agent: Agent; statistics: AgentStats; poe_stats: PoEStats }> {
  return fetchJSON(`${API_BASE_URL}/agents/${aaipAgentId}`);
}

export async function getBadge(aaipAgentId: string): Promise<Badge> {
  return fetchJSON<Badge>(`${API_BASE_URL}/agents/${aaipAgentId}/badge`);
}

// ─────────────────────────────────────────────
// Evaluation
// ─────────────────────────────────────────────

export async function evaluateAgent(request: EvaluationRequest): Promise<Evaluation> {
  return fetchJSON<Evaluation>(`${API_BASE_URL}/evaluate`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function getAgentEvaluations(aaipAgentId: string, limit = 20) {
  return fetchJSON<{ agent_id: string; evaluations: Evaluation[]; count: number }>(
    `${API_BASE_URL}/agents/${aaipAgentId}/evaluations?limit=${limit}`
  );
}

export async function getJob(jobId: string) {
  return fetchJSON<{ job_id: string; status: string; result: any; error: string | null }>(
    `${API_BASE_URL}/jobs/${jobId}`
  );
}

// ─────────────────────────────────────────────
// PoE Traces
// ─────────────────────────────────────────────

export async function submitTrace(agentId: string, trace: object, poeHash?: string) {
  return fetchJSON(`${API_BASE_URL}/traces/submit`, {
    method: 'POST',
    body: JSON.stringify({ agent_id: agentId, trace, poe_hash: poeHash }),
  });
}

export async function verifyTrace(traceId: string) {
  return fetchJSON(`${API_BASE_URL}/traces/${traceId}/verify`);
}

export async function getAgentTraces(aaipAgentId: string, limit = 20) {
  return fetchJSON(`${API_BASE_URL}/agents/${aaipAgentId}/traces?limit=${limit}`);
}

// ─────────────────────────────────────────────
// Reputation & Leaderboard
// ─────────────────────────────────────────────

export async function getReputation(aaipAgentId: string, days = 30): Promise<ReputationTimeline> {
  return fetchJSON<ReputationTimeline>(`${API_BASE_URL}/agents/${aaipAgentId}/reputation?days=${days}`);
}

export async function getLeaderboard(limit = 20, domain?: string) {
  const params = new URLSearchParams({ limit: limit.toString() });
  if (domain) params.append('domain', domain);
  return fetchJSON<{ leaderboard: LeaderboardEntry[]; total_agents: number; domain_filter: string | null }>(
    `${API_BASE_URL}/leaderboard?${params}`
  );
}

// ─────────────────────────────────────────────
// Payments
// ─────────────────────────────────────────────

export async function getPaymentQuote(agentId: string, chain = 'base'): Promise<PaymentQuote> {
  return fetchJSON<PaymentQuote>(`${API_BASE_URL}/payments/quote`, {
    method: 'POST',
    body: JSON.stringify({ agent_id: agentId, chain }),
  });
}

export async function verifyPayment(txHash: string, chain = 'base') {
  return fetchJSON(`${API_BASE_URL}/payments/verify`, {
    method: 'POST',
    body: JSON.stringify({ tx_hash: txHash, chain }),
  });
}

export async function getSupportedChains() {
  return fetchJSON<{ chains: Array<{ id: string; name: string; usdc: boolean }> }>(
    `${API_BASE_URL}/payments/chains`
  );
}

export async function getAgentBalance(aaipAgentId: string) {
  return fetchJSON(`${API_BASE_URL}/agents/${aaipAgentId}/balance`);
}

// ─────────────────────────────────────────────
// CAV
// ─────────────────────────────────────────────

export async function getCAVStatus(aaipAgentId: string): Promise<CAVStatus> {
  return fetchJSON<CAVStatus>(`${API_BASE_URL}/cav/agents/${aaipAgentId}/status`);
}

export async function getCAVHistory(aaipAgentId: string, limit = 20) {
  return fetchJSON(`${API_BASE_URL}/cav/agents/${aaipAgentId}/history?limit=${limit}`);
}

// ─────────────────────────────────────────────
// Shadow Mode
// ─────────────────────────────────────────────

export async function startShadowSession(aaipAgentId: string): Promise<ShadowSession> {
  return fetchJSON<ShadowSession>(`${API_BASE_URL}/shadow/sessions`, {
    method: 'POST',
    body: JSON.stringify({ aaip_agent_id: aaipAgentId }),
  });
}

export async function runShadowEvaluation(sessionId: string, task: string, output: string, trace?: object) {
  return fetchJSON<ShadowReport>(`${API_BASE_URL}/shadow/sessions/${sessionId}/run`, {
    method: 'POST',
    body: JSON.stringify({ task_description: task, agent_output: output, trace }),
  });
}

export async function getShadowReport(sessionId: string): Promise<ShadowReport> {
  return fetchJSON<ShadowReport>(`${API_BASE_URL}/shadow/sessions/${sessionId}/report`);
}

// ─────────────────────────────────────────────
// System
// ─────────────────────────────────────────────

export async function getNetworkStats(): Promise<NetworkStats> {
  return fetchJSON<NetworkStats>(`${API_BASE_URL}/stats/network`);
}

export async function getDomainJudges(domain: string) {
  return fetchJSON<{ domain: string; judges: any[] }>(`${API_BASE_URL}/benchmarks/${domain}/judges`);
}

export async function getDomains() {
  return fetchJSON<{ domains: Array<{ domain: string; agent_count: number }> }>(`${API_BASE_URL}/domains`);
}
