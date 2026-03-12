'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import {
  listAgents,
  getNetworkStats,
  registerAgent,
  evaluateAgent,
  getLeaderboard,
} from '@/lib/api'

// Icons as SVG components
const DashboardIcon = () => (
  <svg className="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
  </svg>
)

const AgentIcon = () => (
  <svg className="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
  </svg>
)

const LeaderboardIcon = () => (
  <svg className="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
  </svg>
)

const EvaluateIcon = () => (
  <svg className="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
  </svg>
)

type Page = 'dashboard' | 'register' | 'evaluate' | 'leaderboard'

export default function Home() {
  const [currentPage, setCurrentPage] = useState<Page>('dashboard')
  const [loading, setLoading] = useState(true)

  // Dashboard state
  const [stats, setStats] = useState<any>(null)
  const [agents, setAgents] = useState<any[]>([])

  // Register state
  const [registerForm, setRegisterForm] = useState({
    company_name: '',
    agent_name: '',
    domain: 'coding',
  })
  const [registeredAgent, setRegisteredAgent] = useState<string | null>(null)
  const [registerError, setRegisterError] = useState<string | null>(null)

  // Evaluate state
  const [evaluateForm, setEvaluateForm] = useState({
    agent_id: '',
    task_domain: 'coding',
    task_description: '',
    agent_output: '',
  })
  const [evaluationResult, setEvaluationResult] = useState<any>(null)
  const [evaluateError, setEvaluateError] = useState<string | null>(null)
  const [evaluating, setEvaluating] = useState(false)

  // Leaderboard state
  const [leaderboard, setLeaderboard] = useState<any[]>([])
  const [leaderboardDomain, setLeaderboardDomain] = useState<string>('')

  useEffect(() => {
    loadDashboardData()
  }, [])

  async function loadDashboardData() {
    try {
      setLoading(true)
      const [statsData, agentsData] = await Promise.all([
        getNetworkStats(),
        listAgents(),
      ])
      setStats(statsData)
      setAgents(agentsData)
    } catch (error) {
      console.error('Failed to load dashboard data:', error)
    } finally {
      setLoading(false)
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    setRegisterError(null)
    setRegisteredAgent(null)

    try {
      const result = await registerAgent(registerForm)
      setRegisteredAgent(result.aaip_agent_id)
      setRegisterForm({ company_name: '', agent_name: '', domain: 'coding' })
      loadDashboardData()
    } catch (error: any) {
      setRegisterError(error.message || 'Failed to register agent')
    }
  }

  async function handleEvaluate(e: React.FormEvent) {
    e.preventDefault()
    setEvaluateError(null)
    setEvaluationResult(null)
    setEvaluating(true)

    try {
      const result = await evaluateAgent(evaluateForm)
      setEvaluationResult(result)
    } catch (error: any) {
      setEvaluateError(error.message || 'Failed to evaluate')
    } finally {
      setEvaluating(false)
    }
  }

  async function loadLeaderboard() {
    try {
      const data = await getLeaderboard(20, leaderboardDomain || undefined)
      setLeaderboard(data.leaderboard)
    } catch (error) {
      console.error('Failed to load leaderboard:', error)
    }
  }

  useEffect(() => {
    if (currentPage === 'leaderboard') {
      loadLeaderboard()
    }
  }, [currentPage, leaderboardDomain])

  function getScoreClass(score: number): string {
    if (score >= 80) return 'high'
    if (score >= 60) return 'medium'
    return 'low'
  }

  function renderPage() {
    switch (currentPage) {
      case 'dashboard':
        return renderDashboard()
      case 'register':
        return renderRegister()
      case 'evaluate':
        return renderEvaluate()
      case 'leaderboard':
        return renderLeaderboard()
      default:
        return renderDashboard()
    }
  }

  function renderDashboard() {
    if (loading) {
      return (
        <div className="loading">
          <div className="spinner"></div>
        </div>
      )
    }

    return (
      <>
        <div className="page-header">
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Overview of the AAIP network</p>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Total Agents</div>
            <div className="stat-value">{stats?.total_agents || 0}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Total Evaluations</div>
            <div className="stat-value">{stats?.total_evaluations || 0}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Network Score</div>
            <div className="stat-value accent">
              {stats?.average_network_score?.toFixed(1) || '0.0'}
            </div>
          </div>
        </div>

        <div className="grid-2">
          <div className="card">
            <div className="card-header">
              <h3 className="card-title">Domain Breakdown</h3>
            </div>
            {stats?.domain_breakdown && Object.keys(stats.domain_breakdown).length > 0 ? (
              <div className="table-container">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Domain</th>
                      <th>Evaluations</th>
                      <th>Avg Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(stats.domain_breakdown).map(([domain, data]: [string, any]) => (
                      <tr key={domain}>
                        <td>
                          <span className={`domain-tag ${domain}`}>{domain}</span>
                        </td>
                        <td>{data.count}</td>
                        <td>{data.average_score.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p style={{ color: '#71717a', padding: '20px', textAlign: 'center' }}>
                No evaluations yet
              </p>
            )}
          </div>

          <div className="card">
            <div className="card-header">
              <h3 className="card-title">Recent Agents</h3>
            </div>
            {agents.length > 0 ? (
              <div className="table-container">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th>Company</th>
                      <th>Domain</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.slice(0, 5).map((agent) => (
                      <tr key={agent.id}>
                        <td style={{ fontFamily: 'monospace', fontSize: '12px' }}>
                          {agent.aaip_agent_id}
                        </td>
                        <td>{agent.company_name}</td>
                        <td>
                          <span className={`domain-tag ${agent.domain}`}>{agent.domain}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p style={{ color: '#71717a', padding: '20px', textAlign: 'center' }}>
                No agents registered yet
              </p>
            )}
          </div>
        </div>
      </>
    )
  }

  function renderRegister() {
    return (
      <>
        <div className="page-header">
          <h1 className="page-title">Register Agent</h1>
          <p className="page-subtitle">Register a new AI agent to get an AAIP Agent ID</p>
        </div>

        <div className="card" style={{ maxWidth: '600px' }}>
          {registerError && (
            <div className="alert alert-error">{registerError}</div>
          )}

          {registeredAgent && (
            <div className="alert alert-success">
              <p style={{ marginBottom: '12px' }}>Agent registered successfully!</p>
              <div className="agent-id-display">
                <span className="agent-id">{registeredAgent}</span>
                <button
                  className="copy-btn"
                  onClick={() => navigator.clipboard.writeText(registeredAgent)}
                >
                  Copy
                </button>
              </div>
            </div>
          )}

          <form onSubmit={handleRegister}>
            <div className="form-group">
              <label className="form-label">Company Name</label>
              <input
                type="text"
                className="form-input"
                placeholder="Enter company name"
                value={registerForm.company_name}
                onChange={(e) => setRegisterForm({ ...registerForm, company_name: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Agent Name</label>
              <input
                type="text"
                className="form-input"
                placeholder="Enter agent name"
                value={registerForm.agent_name}
                onChange={(e) => setRegisterForm({ ...registerForm, agent_name: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Domain</label>
              <select
                className="form-select"
                value={registerForm.domain}
                onChange={(e) => setRegisterForm({ ...registerForm, domain: e.target.value })}
              >
                <option value="coding">Coding</option>
                <option value="finance">Finance</option>
                <option value="general">General Reasoning</option>
              </select>
            </div>

            <button type="submit" className="btn btn-primary" style={{ width: '100%' }}>
              Register Agent
            </button>
          </form>
        </div>
      </>
    )
  }

  function renderEvaluate() {
    return (
      <>
        <div className="page-header">
          <h1 className="page-title">Evaluate Agent</h1>
          <p className="page-subtitle">Submit an agent output for evaluation by judge models</p>
        </div>

        <div className="grid-2">
          <div className="card">
            {evaluateError && (
              <div className="alert alert-error">{evaluateError}</div>
            )}

            <form onSubmit={handleEvaluate}>
              <div className="form-group">
                <label className="form-label">AAIP Agent ID</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="company/agent/xxxxxx"
                  value={evaluateForm.agent_id}
                  onChange={(e) => setEvaluateForm({ ...evaluateForm, agent_id: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label">Task Domain</label>
                <select
                  className="form-select"
                  value={evaluateForm.task_domain}
                  onChange={(e) => setEvaluateForm({ ...evaluateForm, task_domain: e.target.value })}
                >
                  <option value="coding">Coding</option>
                  <option value="finance">Finance</option>
                  <option value="general">General Reasoning</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Task Description</label>
                <textarea
                  className="form-textarea"
                  placeholder="Describe the task the agent was asked to perform..."
                  value={evaluateForm.task_description}
                  onChange={(e) => setEvaluateForm({ ...evaluateForm, task_description: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label">Agent Output</label>
                <textarea
                  className="form-textarea"
                  style={{ minHeight: '200px' }}
                  placeholder="Paste the agent's output here..."
                  value={evaluateForm.agent_output}
                  onChange={(e) => setEvaluateForm({ ...evaluateForm, agent_output: e.target.value })}
                  required
                />
              </div>

              <button
                type="submit"
                className="btn btn-primary"
                style={{ width: '100%' }}
                disabled={evaluating}
              >
                {evaluating ? 'Evaluating...' : 'Run Evaluation'}
              </button>
            </form>
          </div>

          {evaluationResult && (
            <div className="card">
              <div className="card-header">
                <h3 className="card-title">Evaluation Results</h3>
              </div>

              <div className="evaluation-result">
                <div className="judge-scores">
                  {Object.entries(evaluationResult.judge_scores).map(([model, score]: [string, any]) => (
                    <div className="judge-score" key={model}>
                      <div className="judge-model">{model.split('/').pop()}</div>
                      <div className="judge-value">{score}</div>
                    </div>
                  ))}
                </div>

                <div className="final-score">
                  <div className="stat-label" style={{ marginBottom: '8px' }}>FINAL AAIP SCORE</div>
                  <div className="final-score-value">{evaluationResult.final_score}</div>
                  <div style={{ marginTop: '12px', color: '#a1a1aa', fontSize: '14px' }}>
                    Variance: {evaluationResult.score_variance?.toFixed(2)} |
                    Agreement: {evaluationResult.agreement_level}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </>
    )
  }

  function renderLeaderboard() {
    return (
      <>
        <div className="page-header">
          <h1 className="page-title">Leaderboard</h1>
          <p className="page-subtitle">Top performing agents by reliability score</p>
        </div>

        <div className="card">
          <div className="form-group" style={{ maxWidth: '300px', marginBottom: '24px' }}>
            <label className="form-label">Filter by Domain</label>
            <select
              className="form-select"
              value={leaderboardDomain}
              onChange={(e) => setLeaderboardDomain(e.target.value)}
            >
              <option value="">All Domains</option>
              <option value="coding">Coding</option>
              <option value="finance">Finance</option>
              <option value="general">General</option>
            </select>
          </div>

          {leaderboard.length > 0 ? (
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Agent</th>
                    <th>Company</th>
                    <th>Domain</th>
                    <th>Evaluations</th>
                    <th>Avg Score</th>
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.map((entry) => (
                    <tr key={entry.aaip_agent_id}>
                      <td style={{ fontWeight: '600' }}>#{entry.rank}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: '12px' }}>
                        {entry.aaip_agent_id}
                      </td>
                      <td>{entry.company_name}</td>
                      <td>
                        <span className={`domain-tag ${entry.domain}`}>{entry.domain}</span>
                      </td>
                      <td>{entry.evaluation_count}</td>
                      <td>
                        <span className={`score-badge ${getScoreClass(entry.average_score)}`}>
                          {entry.average_score.toFixed(1)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p style={{ color: '#71717a', padding: '40px', textAlign: 'center' }}>
              No leaderboard data available yet
            </p>
          )}
        </div>
      </>
    )
  }

  return (
    <div className="container">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-icon">A</div>
          <span className="logo-text">AAIP</span>
        </div>

        <nav className="nav-menu">
          <button
            className={`nav-item ${currentPage === 'dashboard' ? 'active' : ''}`}
            onClick={() => setCurrentPage('dashboard')}
          >
            <DashboardIcon />
            Dashboard
          </button>
          <button
            className={`nav-item ${currentPage === 'register' ? 'active' : ''}`}
            onClick={() => setCurrentPage('register')}
          >
            <AgentIcon />
            Register Agent
          </button>
          <button
            className={`nav-item ${currentPage === 'evaluate' ? 'active' : ''}`}
            onClick={() => setCurrentPage('evaluate')}
          >
            <EvaluateIcon />
            Evaluate
          </button>
          <button
            className={`nav-item ${currentPage === 'leaderboard' ? 'active' : ''}`}
            onClick={() => setCurrentPage('leaderboard')}
          >
            <LeaderboardIcon />
            Leaderboard
          </button>
        </nav>
      </aside>

      <main className="main-content">
        {renderPage()}
      </main>
    </div>
  )
}
