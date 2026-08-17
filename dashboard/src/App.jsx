import React, { useEffect, useState } from 'react'
import axios from 'axios'
import './index.css'

const API_URL = (
  import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')
).replace(/\/$/, '')
const REFRESH_INTERVAL_MS = 5000
const TIME_ZONE = 'Asia/Kolkata'

const ACTION_LABELS = {
  get_upstream_state: 'Checked state',
  open_circuit: 'Opened circuit',
  close_circuit: 'Closed circuit',
  drain_upstream: 'Drained upstream',
  mark_resolved: 'Marked resolved'
}

const compactActionName = (action) => ACTION_LABELS[action] || action.replaceAll('_', ' ')

const EVENT_LABELS = {
  health_failed: 'Health failed',
  health_still_unhealthy: 'Still unhealthy',
  circuit_half_open: 'Trial opened',
  circuit_closed: 'Circuit closed',
  upstream_request_failed: 'Request failed',
  healing_completed: 'Healing completed'
}

function LandingPage() {
  return (
    <div className="landing-container">
      <header className="landing-header">
        <a className="brand-link" href="/" aria-label="Self-Healing API Gateway home">
          Self-Healing API Gateway
        </a>
        <a className="secondary-link" href="/dashboard">
          Open dashboard
        </a>
      </header>

      <main>
        <section className="hero-section">
          <div className="hero-kicker">
            <span className="status-dot healthy"></span>
            Autonomous resilience control plane
          </div>
          <h1 className="hero-title">Keep upstream failures contained.</h1>
          <p className="hero-copy">
            Detect unhealthy services, isolate failure with circuit breakers, and
            coordinate AI-assisted recovery from one operational view.
          </p>
          <div className="hero-actions">
            <a className="primary-link" href="/dashboard">
              Enter control plane <span aria-hidden="true">→</span>
            </a>
            <a className="text-link" href="#capabilities">See how it works</a>
          </div>
        </section>

        <section className="capabilities-section" id="capabilities">
          <h2 className="section-title">Resilience loop</h2>
          <div className="capability-grid">
            <article className="capability-card">
              <span className="capability-index">01</span>
              <h3>Detect</h3>
              <p>Continuously check upstream health and classify repeated failures.</p>
            </article>
            <article className="capability-card">
              <span className="capability-index">02</span>
              <h3>Isolate</h3>
              <p>Open health-gated circuits before a dependency failure spreads.</p>
            </article>
            <article className="capability-card">
              <span className="capability-index">03</span>
              <h3>Recover</h3>
              <p>Run assisted remediation and preserve a complete operator audit trail.</p>
            </article>
          </div>
        </section>
      </main>
    </div>
  )
}

function DashboardPage() {
  const [gatewayStatus, setGatewayStatus] = useState({})
  const [gatewaySummary, setGatewaySummary] = useState(null)
  const [auditSessions, setAuditSessions] = useState([])
  const [gatewayEvents, setGatewayEvents] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [lastUpdated, setLastUpdated] = useState(null)
  const [expandedActions, setExpandedActions] = useState({})

  const fetchData = async ({ signal, showLoading = false } = {}) => {
    if (showLoading) {
      setIsLoading(true)
    } else {
      setIsRefreshing(true)
    }

    try {
      const [statusRes, summaryRes, auditRes, eventsRes] = await Promise.all([
        axios.get(`${API_URL}/gateway/health-status`, { signal }),
        axios.get(`${API_URL}/gateway/summary`, { signal }),
        axios.get(`${API_URL}/audit/sessions`, { signal }),
        axios.get(`${API_URL}/audit/events`, { signal })
      ])
      setGatewayStatus(statusRes.data)
      setGatewaySummary(summaryRes.data)
      setAuditSessions(auditRes.data)
      setGatewayEvents(eventsRes.data)
      setErrorMessage('')
      setLastUpdated(new Date())
    } catch (error) {
      if (axios.isCancel(error)) return
      console.error('Error fetching data:', error)
      setErrorMessage('Unable to reach the gateway API.')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    fetchData({ signal: controller.signal, showLoading: true })
    const interval = setInterval(() => {
      fetchData({ signal: controller.signal })
    }, REFRESH_INTERVAL_MS)
    return () => {
      controller.abort()
      clearInterval(interval)
    }
  }, [])

  const formatDate = (dateString) => {
    if (!dateString) return '-'
    const date = new Date(dateString)

    const options = {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
      timeZone: TIME_ZONE,
      timeZoneName: 'short'
    }
    return date.toLocaleString('en-IN', options)
  }

  const formatLastUpdated = () => {
    if (!lastUpdated) return 'Not updated yet'
    return `Updated ${formatDate(lastUpdated.toISOString())}`
  }

  const formatReason = (session) => {
    return session.reason || 'Gemini did not provide a healing summary.'
  }

  const compactActions = (actions = []) => {
    return {
      visible: actions.slice(0, 2),
      hidden: actions.slice(2),
      totalCount: actions.length
    }
  }

  const toggleActions = (sessionId) => {
    setExpandedActions(current => ({
      ...current,
      [sessionId]: !current[sessionId]
    }))
  }

  const upstreamEntries = Object.entries(gatewayStatus)
  const knownUpstreams = new Set(upstreamEntries.map(([url]) => url))
  const visibleGatewayEvents = gatewayEvents.filter(event => (
    !event.upstream_url || knownUpstreams.has(event.upstream_url)
  ))
  const summaryItems = [
    ['Healthy', gatewaySummary?.healthy_upstreams ?? 0],
    ['Unhealthy', gatewaySummary?.unhealthy_upstreams ?? 0],
    ['Open', gatewaySummary?.open_circuits ?? 0],
    ['Half-open', gatewaySummary?.half_open_circuits ?? 0]
  ]

  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <div>
          <a className="back-link" href="/">← Overview</a>
          <h1 className="dashboard-title">Self-Healing API Gateway</h1>
          <div className="dashboard-subtitle">Self-healing infrastructure control plane</div>
        </div>
        <div className="header-actions">
          <span className="last-updated">{formatLastUpdated()}</span>
          <button
            className="refresh-button"
            type="button"
            disabled={isRefreshing}
            onClick={() => fetchData()}
          >
            {isRefreshing ? 'Refreshing' : 'Refresh'}
          </button>
        </div>
      </header>

      {errorMessage && (
        <div className="alert-banner" role="status">
          {errorMessage}
        </div>
      )}

      <section>
        <div className="summary-grid">
          {summaryItems.map(([label, value]) => (
            <div className="summary-item" key={label}>
              <span className="summary-label">{label}</span>
              <span className="summary-value">{value}</span>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="section-title">Upstreams</h2>
        <div className="upstreams-list">
          {upstreamEntries.map(([url, data]) => (
            <div className="upstream-item" key={url}>
              <div className="upstream-url">{url}</div>

              <div className="status-label">
                <div className={`status-dot ${data.is_healthy ? 'healthy' : 'unhealthy'}`}></div>
                {data.is_healthy ? 'Healthy' : 'Unhealthy'}
              </div>

              <div className="metric-group">
                <span className="metric-label">Circuit</span>
                <span className={`metric-value cb-${String(data.circuit_state).toLowerCase()}`}>
                  {data.circuit_state || 'UNKNOWN'}
                </span>
              </div>

              <div className="metric-group">
                <span className="metric-label">Failures</span>
                <span className="metric-value">{data.failure_count}</span>
              </div>
            </div>
          ))}
          {!isLoading && upstreamEntries.length === 0 && (
            <div className="empty-state">No upstreams reported by the gateway.</div>
          )}
          {isLoading && (
            <div className="empty-state">Loading upstream status...</div>
          )}
        </div>
      </section>

      <section>
        <h2 className="section-title">Recent Timeline</h2>
        <div className="timeline-list">
          {visibleGatewayEvents.slice(0, 8).map(event => (
            <div className="timeline-item" key={event.event_id}>
              <div className="timeline-time">{formatDate(event.occurred_at)}</div>
              <div className="timeline-main">
                <div className="timeline-title">
                  {EVENT_LABELS[event.event_type] || event.event_type.replaceAll('_', ' ')}
                </div>
                <div className="timeline-message">{event.message}</div>
              </div>
              <div className="timeline-target">{event.upstream_url || '-'}</div>
            </div>
          ))}
          {!isLoading && visibleGatewayEvents.length === 0 && (
            <div className="empty-state">No gateway events recorded yet.</div>
          )}
          {isLoading && (
            <div className="empty-state">Loading gateway timeline...</div>
          )}
        </div>
      </section>

      <section>
        <h2 className="section-title">Audit Log</h2>
        <div className="audit-list">
          <div className="audit-header">
            <div>Timestamp</div>
            <div>Target</div>
            <div>Status</div>
            <div>Reason</div>
            <div>Actions Taken</div>
          </div>
          
          {auditSessions.map(session => (
            <div className="audit-row" key={session.session_id}>
              <div className="timestamp">{formatDate(session.triggered_at)}</div>
              <div className="upstream-url">{session.upstream_url}</div>
              <div className={`status-text ${session.status === 'resolved' ? 'status-resolved' : 'status-issue'}`}>
                {session.status === 'resolved' ? 'Resolved' : 'Escalated'}
              </div>
              <div className="reason-text">
                {formatReason(session)}
              </div>
              <div className="tag-list">
                {session.actions_taken && session.actions_taken.length > 0 ? (() => {
                  const actions = compactActions(session.actions_taken)
                  const isExpanded = expandedActions[session.session_id]
                  const visibleActions = isExpanded
                    ? session.actions_taken
                    : actions.visible
                  return (
                    <>
                      {visibleActions.map((action, idx) => (
                        <span key={`${action}-${idx}`} className="action-tag">
                          {compactActionName(action)}
                        </span>
                      ))}
                      {actions.hidden.length > 0 && (
                        <button
                          type="button"
                          className="action-expand"
                          onClick={() => toggleActions(session.session_id)}
                          aria-expanded={Boolean(isExpanded)}
                        >
                          {isExpanded ? 'Show less' : `+${actions.hidden.length}`}
                        </button>
                      )}
                      <span className="action-count">{actions.totalCount} steps</span>
                    </>
                  )
                })() : (
                  <span className="muted-text">-</span>
                )}
              </div>
            </div>
          ))}
          {!isLoading && auditSessions.length === 0 && (
            <div className="empty-state">No healing sessions recorded yet.</div>
          )}
          {isLoading && (
            <div className="empty-state">Loading audit sessions...</div>
          )}
        </div>
      </section>
    </div>
  )
}

function App() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  return path === '/dashboard'
    ? <DashboardPage />
    : <LandingPage />
}

export default App
