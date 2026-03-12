//! AAIP Rust SDK — Autonomous Agent Infrastructure Protocol
//! https://aaip.dev
//!
//! # Quick Start
//!
//! ```rust,no_run
//! use aaip::{AAIPClient, AgentManifest};
//!
//! #[tokio::main]
//! async fn main() {
//!     let client = AAIPClient::new("your-api-key", None);
//!
//!     let manifest = AgentManifest {
//!         agent_name: "MyAgent".to_string(),
//!         owner: "YourCo".to_string(),
//!         endpoint: "https://api.yourco.com/agent".to_string(),
//!         capabilities: vec!["code_analysis".to_string(), "translation".to_string()],
//!         framework: Some("custom".to_string()),
//!         ..Default::default()
//!     };
//!
//!     let result = client.register(&manifest).await.unwrap();
//!     println!("Registered: {:?}", result);
//! }
//! ```

use reqwest::{Client, header};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::env;
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

// ─────────────────────────────────────────────
// Errors
// ─────────────────────────────────────────────

#[derive(Error, Debug)]
pub enum AAIPError {
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("Authentication error: invalid or missing API key")]
    Auth,
    #[error("Not found: {0}")]
    NotFound(String),
    #[error("Validation error: {0}")]
    Validation(String),
    #[error("API error {status}: {message}")]
    Api { status: u16, message: String },
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

pub type Result<T> = std::result::Result<T, AAIPError>;

// ─────────────────────────────────────────────
// Models
// ─────────────────────────────────────────────

/// Agent manifest — describes your agent for AAIP registration.
/// AAIP does not create your agent. You register one you already built.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AgentManifest {
    pub agent_name: String,
    pub owner: String,
    pub endpoint: String,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub description: String,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub version: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub capabilities: Vec<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub domains: Vec<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub tools: Vec<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub tags: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub framework: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub public_key: Option<String>,
}

/// A single verifiable step in agent execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PoETraceStep {
    pub step_type: String,
    pub name: String,
    pub timestamp_ms: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latency_ms: Option<u64>,
    pub status: String,
}

/// Proof-of-Execution trace — verifiable record of agent execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PoETrace {
    pub task_id: String,
    pub agent_id: String,
    pub task_description: String,
    pub started_at_ms: u64,
    pub completed_at_ms: u64,
    pub steps: Vec<PoETraceStep>,
    pub total_tool_calls: u32,
    pub total_llm_calls: u32,
    pub total_api_calls: u32,
    pub tool_calls: Vec<Value>,
    pub reasoning_steps: Vec<Value>,
    pub token_usage: HashMap<String, u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub poe_hash: Option<String>,
}

impl PoETrace {
    pub fn new(task_id: &str, agent_id: &str, task_description: &str) -> Self {
        Self {
            task_id: task_id.to_string(),
            agent_id: agent_id.to_string(),
            task_description: task_description.to_string(),
            started_at_ms: now_ms(),
            completed_at_ms: 0,
            steps: Vec::new(),
            total_tool_calls: 0,
            total_llm_calls: 0,
            total_api_calls: 0,
            tool_calls: Vec::new(),
            reasoning_steps: Vec::new(),
            token_usage: HashMap::new(),
            poe_hash: None,
        }
    }

    pub fn add_tool(&mut self, name: &str, latency_ms: u64) {
        self.steps.push(PoETraceStep {
            step_type: "tool_call".into(),
            name: name.to_string(),
            timestamp_ms: now_ms(),
            input_hash: None,
            output_hash: None,
            latency_ms: Some(latency_ms),
            status: "success".into(),
        });
        self.total_tool_calls += 1;
        self.tool_calls.push(json!({"tool": name, "latency_ms": latency_ms}));
    }

    pub fn add_reasoning(&mut self, thought: &str) {
        let hash = sha256_short(thought);
        self.steps.push(PoETraceStep {
            step_type: "reasoning".into(),
            name: "reasoning".into(),
            timestamp_ms: now_ms(),
            input_hash: None,
            output_hash: Some(hash.clone()),
            latency_ms: None,
            status: "success".into(),
        });
        self.reasoning_steps.push(json!({"hash": hash}));
    }

    pub fn add_llm_call(&mut self, model: &str, tokens_in: u64, tokens_out: u64, latency_ms: u64) {
        self.steps.push(PoETraceStep {
            step_type: "llm_call".into(),
            name: model.to_string(),
            timestamp_ms: now_ms(),
            input_hash: None,
            output_hash: None,
            latency_ms: Some(latency_ms),
            status: "success".into(),
        });
        self.total_llm_calls += 1;
        let total = self.token_usage.entry("total_tokens".into()).or_insert(0);
        *total += tokens_in + tokens_out;
    }

    pub fn finish(&mut self) {
        self.completed_at_ms = now_ms();
        self.poe_hash = Some(self.compute_hash());
    }

    pub fn compute_hash(&self) -> String {
        let mut data = format!("{}:{}:{}", self.task_id, self.agent_id, self.started_at_ms);
        for s in &self.steps {
            data.push_str(&format!(":{}:{}:{}:{}", s.step_type, s.name, s.timestamp_ms, s.status));
        }
        let mut hasher = Sha256::new();
        hasher.update(data.as_bytes());
        format!("{:x}", hasher.finalize())
    }
}

/// Evaluation response from the AI jury.
#[derive(Debug, Deserialize)]
pub struct EvaluationResponse {
    pub evaluation_id: String,
    pub agent_id: String,
    pub task_domain: String,
    pub judge_scores: HashMap<String, f64>,
    pub final_score: f64,
    pub score_variance: f64,
    pub agreement_level: String,
    pub poe_verified: bool,
    pub poe_hash: Option<String>,
}

/// Agent found in discovery.
#[derive(Debug, Deserialize)]
pub struct DiscoveryResult {
    pub aaip_agent_id: String,
    pub agent_name: String,
    pub owner: String,
    pub description: Option<String>,
    pub capabilities: Option<Vec<String>>,
    pub framework: Option<String>,
    pub reputation_score: Option<f64>,
}

// ─────────────────────────────────────────────
// Client
// ─────────────────────────────────────────────

pub struct AAIPClient {
    api_key: String,
    base_url: String,
    client: Client,
}

impl AAIPClient {
    pub fn new(api_key: &str, base_url: Option<&str>) -> Self {
        let key = if api_key.is_empty() {
            env::var("AAIP_API_KEY").unwrap_or_default()
        } else {
            api_key.to_string()
        };
        let url = base_url
            .map(|u| u.to_string())
            .unwrap_or_else(|| env::var("AAIP_BASE_URL").unwrap_or_else(|_| "https://api.aaip.dev".to_string()));

        Self {
            api_key: key,
            base_url: url.trim_end_matches('/').to_string(),
            client: Client::new(),
        }
    }

    fn url(&self, path: &str) -> String {
        format!("{}/{}", self.base_url, path.trim_start_matches('/'))
    }

    fn headers(&self) -> header::HeaderMap {
        let mut map = header::HeaderMap::new();
        map.insert(header::CONTENT_TYPE, "application/json".parse().unwrap());
        map.insert("User-Agent", "aaip-rust-sdk/1.0.0".parse().unwrap());
        map.insert("X-AAIP-Version", "1".parse().unwrap());
        if !self.api_key.is_empty() {
            map.insert(
                header::AUTHORIZATION,
                format!("Bearer {}", self.api_key).parse().unwrap(),
            );
        }
        map
    }

    async fn post(&self, path: &str, body: Value) -> Result<Value> {
        let res = self.client
            .post(self.url(path))
            .headers(self.headers())
            .json(&body)
            .send()
            .await?;

        let status = res.status().as_u16();
        let text = res.text().await?;

        match status {
            200..=299 => Ok(serde_json::from_str(&text)?),
            401 => Err(AAIPError::Auth),
            404 => Err(AAIPError::NotFound(path.to_string())),
            422 => Err(AAIPError::Validation(text)),
            _ => Err(AAIPError::Api { status, message: text }),
        }
    }

    async fn get(&self, path: &str, params: Option<&[(&str, &str)]>) -> Result<Value> {
        let mut url = self.url(path);
        if let Some(p) = params {
            let qs: String = p.iter()
                .map(|(k, v)| format!("{}={}", k, v))
                .collect::<Vec<_>>()
                .join("&");
            if !qs.is_empty() {
                url = format!("{}?{}", url, qs);
            }
        }

        let res = self.client.get(&url).headers(self.headers()).send().await?;
        let status = res.status().as_u16();
        let text = res.text().await?;

        match status {
            200..=299 => Ok(serde_json::from_str(&text)?),
            401 => Err(AAIPError::Auth),
            404 => Err(AAIPError::NotFound(path.to_string())),
            _ => Err(AAIPError::Api { status, message: text }),
        }
    }

    // ── Registration ─────────────────────

    pub async fn register(&self, manifest: &AgentManifest) -> Result<Value> {
        self.post("discovery/register", json!({"manifest": manifest})).await
    }

    pub async fn get_agent(&self, agent_id: &str) -> Result<Value> {
        self.get(&format!("agents/{}", agent_id), None).await
    }

    // ── Discovery ────────────────────────

    pub async fn discover(&self, capability: Option<&str>, domain: Option<&str>, limit: u32) -> Result<Vec<DiscoveryResult>> {
        let limit_str = limit.to_string();
        let mut params: Vec<(&str, &str)> = vec![("limit", &limit_str)];
        if let Some(c) = capability { params.push(("capability", c)); }
        if let Some(d) = domain { params.push(("domain", d)); }

        let val = self.get("discovery/agents", Some(&params)).await?;
        let agents: Vec<DiscoveryResult> = serde_json::from_value(val["agents"].clone())?;
        Ok(agents)
    }

    // ── Evaluation ───────────────────────

    pub async fn evaluate(
        &self,
        agent_id: &str,
        task_desc: &str,
        output: &str,
        domain: &str,
        trace: Option<&mut PoETrace>,
    ) -> Result<EvaluationResponse> {
        let mut body = json!({
            "agent_id": agent_id,
            "task_domain": domain,
            "task_description": task_desc,
            "agent_output": output,
            "async_mode": false,
        });

        if let Some(t) = trace {
            t.finish();
            body["trace"] = serde_json::to_value(&t)?;
        }

        let val = self.post("evaluate", body).await?;
        Ok(serde_json::from_value(val)?)
    }

    // ── Proof of Execution ───────────────

    pub async fn submit_trace(&self, agent_id: &str, trace: &mut PoETrace) -> Result<Value> {
        trace.finish();
        self.post("traces/submit", json!({
            "agent_id": agent_id,
            "trace": trace,
            "poe_hash": trace.poe_hash,
        })).await
    }

    // ── Reputation ───────────────────────

    pub async fn get_reputation(&self, agent_id: &str, days: u32) -> Result<Value> {
        let days_str = days.to_string();
        self.get(
            &format!("agents/{}/reputation", agent_id),
            Some(&[("days", &days_str)]),
        ).await
    }

    pub async fn health(&self) -> Result<Value> {
        self.get("health", None).await
    }
}

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time error")
        .as_millis() as u64
}

fn sha256_short(data: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data.as_bytes());
    format!("{:x}", hasher.finalize())[..16].to_string()
}
