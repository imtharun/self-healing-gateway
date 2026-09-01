import React, { useEffect, useRef, useState } from 'react'
import './index.css'

const TIME_ZONE = 'Asia/Kolkata'
const PAYMENTS_UPSTREAM = 'payments.demo.internal'
const ORDERS_UPSTREAM = 'orders.demo.internal'
const API_URL = (
  import.meta.env.DEV
    ? (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000')
    : '/backend'
).replace(/\/$/, '')

const apiRequest = async (path, options = {}) => {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(data.detail || 'The gateway request failed.')
    error.status = response.status
    throw error
  }
  return data
}

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
  circuit_opened: 'Circuit opened',
  circuit_half_open: 'Trial opened',
  circuit_closed: 'Circuit closed',
  upstream_request_failed: 'Request failed',
  healing_completed: 'Healing completed'
}

const dateBefore = (minutes) => new Date(Date.now() - minutes * 60_000).toISOString()

const createSeededDemoData = () => ({
  gatewayStatus: {
    [PAYMENTS_UPSTREAM]: {
      is_healthy: true,
      circuit_state: 'CLOSED',
      failure_count: 0
    },
    [ORDERS_UPSTREAM]: {
      is_healthy: true,
      circuit_state: 'CLOSED',
      failure_count: 0
    }
  },
  gatewayEvents: [
    {
      event_id: 'seed-healing-completed',
      event_type: 'healing_completed',
      occurred_at: dateBefore(8),
      message: 'Recovery verified and normal traffic restored.',
      upstream_url: ORDERS_UPSTREAM
    },
    {
      event_id: 'seed-circuit-closed',
      event_type: 'circuit_closed',
      occurred_at: dateBefore(9),
      message: 'Health probes passed; circuit returned to closed.',
      upstream_url: ORDERS_UPSTREAM
    },
    {
      event_id: 'seed-health-failed',
      event_type: 'health_failed',
      occurred_at: dateBefore(12),
      message: 'Three consecutive health checks exceeded the failure threshold.',
      upstream_url: ORDERS_UPSTREAM
    }
  ],
  auditSessions: [
    {
      session_id: 'seed-session-001',
      triggered_at: dateBefore(12),
      upstream_url: ORDERS_UPSTREAM,
      status: 'resolved',
      reason: 'Repeated health-check failures were isolated before recovery was verified.',
      actions_taken: ['get_upstream_state', 'open_circuit', 'drain_upstream', 'close_circuit', 'mark_resolved']
    }
  ]
})

function LandingPage() {
  return (
    <div className="landing-container">
      <header className="landing-header">
        <a className="brand-link" href="/" aria-label="Self-Healing API Gateway home">
          Self-Healing API Gateway
        </a>
        <div className="landing-nav-actions">
          <a className="text-link" href="/operator/login">Operator login</a>
          <a className="secondary-link" href="/dashboard">
            Open dashboard
          </a>
        </div>
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

function DashboardPage({ operatorMode = false }) {
  const [demoData, setDemoData] = useState(createSeededDemoData)
  const [operatorData, setOperatorData] = useState({
    gatewayStatus: {},
    gatewaySummary: null,
    gatewayEvents: [],
    auditSessions: []
  })
  const [demoPhase, setDemoPhase] = useState('ready')
  const [lastUpdated, setLastUpdated] = useState(() => operatorMode ? null : new Date())
  const [expandedActions, setExpandedActions] = useState({})
  const [isLoading, setIsLoading] = useState(operatorMode)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [operatorAuthenticated, setOperatorAuthenticated] = useState(!operatorMode)
  const timersRef = useRef([])

  useEffect(() => {
    return () => {
      timersRef.current.forEach(clearTimeout)
    }
  }, [])

  const fetchOperatorData = async ({ signal, initial = false } = {}) => {
    if (initial) setIsLoading(true)
    else setIsRefreshing(true)

    try {
      await apiRequest('/auth/session', { signal })
      setOperatorAuthenticated(true)
      const [gatewayStatus, gatewaySummary, auditSessions, gatewayEvents] = await Promise.all([
        apiRequest('/gateway/health-status', { signal }),
        apiRequest('/gateway/summary', { signal }),
        apiRequest('/audit/sessions', { signal }),
        apiRequest('/audit/events', { signal })
      ])
      setOperatorData({ gatewayStatus, gatewaySummary, auditSessions, gatewayEvents })
      setErrorMessage('')
      setLastUpdated(new Date())
    } catch (error) {
      if (error.name === 'AbortError') return
      if (error.status === 401) {
        window.location.replace('/operator/login')
        return
      }
      setErrorMessage(error.message || 'Unable to reach the gateway API.')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }

  useEffect(() => {
    if (!operatorMode) return undefined
    const controller = new AbortController()
    fetchOperatorData({ signal: controller.signal, initial: true })
    return () => controller.abort()
  }, [operatorMode])

  const logoutOperator = async () => {
    try {
      await apiRequest('/auth/logout', {
        method: 'POST',
        headers: { 'X-Operator-CSRF': '1' }
      })
    } finally {
      window.location.replace('/operator/login')
    }
  }

  const addTimer = (callback, delay) => {
    const timer = setTimeout(callback, delay)
    timersRef.current.push(timer)
  }

  const addEvent = (current, event) => ({
    ...current,
    gatewayEvents: [event, ...current.gatewayEvents]
  })

  const runIncidentDemo = () => {
    timersRef.current.forEach(clearTimeout)
    timersRef.current = []
    setExpandedActions({})

    const incidentId = `demo-${Date.now()}`
    const startedAt = new Date().toISOString()
    const baseline = createSeededDemoData()
    setDemoPhase('detecting')
    setLastUpdated(new Date())
    setDemoData(addEvent({
      ...baseline,
      gatewayStatus: {
        ...baseline.gatewayStatus,
        [ORDERS_UPSTREAM]: {
          is_healthy: false,
          circuit_state: 'CLOSED',
          failure_count: 3
        }
      }
    }, {
      event_id: `${incidentId}-detected`,
      event_type: 'health_failed',
      occurred_at: startedAt,
      message: 'Failure threshold reached after three unsuccessful health checks.',
      upstream_url: ORDERS_UPSTREAM
    }))

    addTimer(() => {
      setDemoPhase('isolating')
      setLastUpdated(new Date())
      setDemoData(current => addEvent({
        ...current,
        gatewayStatus: {
          ...current.gatewayStatus,
          [ORDERS_UPSTREAM]: {
            is_healthy: false,
            circuit_state: 'OPEN',
            failure_count: 3
          }
        }
      }, {
        event_id: `${incidentId}-isolated`,
        event_type: 'circuit_opened',
        occurred_at: new Date().toISOString(),
        message: 'Circuit opened to contain the failing dependency.',
        upstream_url: ORDERS_UPSTREAM
      }))
    }, 1400)

    addTimer(() => {
      setDemoPhase('recovering')
      setLastUpdated(new Date())
      setDemoData(current => addEvent({
        ...current,
        gatewayStatus: {
          ...current.gatewayStatus,
          [ORDERS_UPSTREAM]: {
            is_healthy: true,
            circuit_state: 'HALF_OPEN',
            failure_count: 0
          }
        }
      }, {
        event_id: `${incidentId}-trial`,
        event_type: 'circuit_half_open',
        occurred_at: new Date().toISOString(),
        message: 'A limited recovery probe was allowed through the circuit.',
        upstream_url: ORDERS_UPSTREAM
      }))
    }, 3000)

    addTimer(() => {
      const resolvedAt = new Date().toISOString()
      setDemoPhase('complete')
      setLastUpdated(new Date())
      setDemoData(current => addEvent({
        ...current,
        gatewayStatus: {
          ...current.gatewayStatus,
          [ORDERS_UPSTREAM]: {
            is_healthy: true,
            circuit_state: 'CLOSED',
            failure_count: 0
          }
        },
        auditSessions: [{
          session_id: incidentId,
          triggered_at: startedAt,
          upstream_url: ORDERS_UPSTREAM,
          status: 'resolved',
          reason: 'The demo policy isolated repeated failures, tested recovery, and restored traffic.',
          actions_taken: ['get_upstream_state', 'open_circuit', 'drain_upstream', 'close_circuit', 'mark_resolved']
        }, ...current.auditSessions]
      }, {
        event_id: `${incidentId}-resolved`,
        event_type: 'healing_completed',
        occurred_at: resolvedAt,
        message: 'Recovery verified; circuit closed and normal traffic restored.',
        upstream_url: ORDERS_UPSTREAM
      }))
    }, 4600)
  }

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

  const activeData = operatorMode ? operatorData : demoData
  const { gatewayStatus, auditSessions, gatewayEvents } = activeData
  const upstreamEntries = Object.entries(gatewayStatus)
  const knownUpstreams = new Set(upstreamEntries.map(([url]) => url))
  const visibleGatewayEvents = gatewayEvents.filter(event => (
    !event.upstream_url || knownUpstreams.has(event.upstream_url)
  ))
  const summaryItems = [
    ['Healthy', operatorMode
      ? (operatorData.gatewaySummary?.healthy_upstreams ?? 0)
      : upstreamEntries.filter(([, data]) => data.is_healthy).length],
    ['Unhealthy', operatorMode
      ? (operatorData.gatewaySummary?.unhealthy_upstreams ?? 0)
      : upstreamEntries.filter(([, data]) => !data.is_healthy).length],
    ['Open', operatorMode
      ? (operatorData.gatewaySummary?.open_circuits ?? 0)
      : upstreamEntries.filter(([, data]) => data.circuit_state === 'OPEN').length],
    ['Half-open', operatorMode
      ? (operatorData.gatewaySummary?.half_open_circuits ?? 0)
      : upstreamEntries.filter(([, data]) => data.circuit_state === 'HALF_OPEN').length]
  ]
  const isDemoRunning = ['detecting', 'isolating', 'recovering'].includes(demoPhase)
  const demoButtonLabel = {
    ready: 'Run incident demo',
    detecting: 'Detecting failure…',
    isolating: 'Isolating service…',
    recovering: 'Verifying recovery…',
    complete: 'Run demo again'
  }[demoPhase]

  if (operatorMode && !operatorAuthenticated) {
    return (
      <main className="auth-shell">
        <section className="auth-panel" aria-labelledby="operator-check-title">
          <a className="back-link" href="/dashboard">← Public demo</a>
          <div className="auth-kicker">
            <span className="status-dot healthy"></span>
            Restricted access
          </div>
          <h1 id="operator-check-title" className="auth-title">Verifying operator session</h1>
          <p className="auth-copy">
            {errorMessage || 'Checking your secure session with the gateway.'}
          </p>
          {errorMessage && (
            <a className="auth-submit auth-link-button" href="/operator/login">
              Go to operator login
            </a>
          )}
        </section>
      </main>
    )
  }

  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <div>
          <a className="back-link" href={operatorMode ? '/dashboard' : '/'}>
            {operatorMode ? '← Public demo' : '← Overview'}
          </a>
          <h1 className="dashboard-title">
            {operatorMode ? 'Operator Control Plane' : 'Self-Healing API Gateway'}
          </h1>
          <div className="dashboard-subtitle">
            {operatorMode
              ? 'Authenticated live infrastructure view'
              : 'Self-healing infrastructure control plane'}
          </div>
        </div>
        <div className="header-actions">
          <span className="last-updated">{formatLastUpdated()}</span>
          <button
            className="refresh-button"
            type="button"
            disabled={operatorMode ? isRefreshing : isDemoRunning}
            onClick={operatorMode ? () => fetchOperatorData() : runIncidentDemo}
          >
            {operatorMode ? (isRefreshing ? 'Refreshing…' : 'Refresh') : demoButtonLabel}
          </button>
          {operatorMode && (
            <button className="text-button" type="button" onClick={logoutOperator}>
              Log out
            </button>
          )}
        </div>
      </header>

      {operatorMode ? (
        <div className="demo-notice" role="status">
          <span className="demo-badge protected-badge">Protected</span>
          <span>Live gateway status and audit records. Operator authentication is required.</span>
        </div>
      ) : (
        <div className="demo-notice" role="status" aria-live="polite">
          <span className="demo-badge">Demo data</span>
          <span>
            Simulated services and incidents. Running this scenario does not affect real infrastructure.
          </span>
          <span className={`demo-phase phase-${demoPhase}`}>{demoPhase}</span>
        </div>
      )}

      {errorMessage && (
        <div className="alert-banner" role="alert">{errorMessage}</div>
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
          {upstreamEntries.length === 0 && (
            <div className="empty-state">
              {isLoading ? 'Loading upstream status…' : 'No upstreams reported by the gateway.'}
            </div>
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
          {visibleGatewayEvents.length === 0 && (
            <div className="empty-state">
              {isLoading ? 'Loading gateway timeline…' : 'No gateway events recorded yet.'}
            </div>
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
          {auditSessions.length === 0 && (
            <div className="empty-state">
              {isLoading ? 'Loading audit sessions…' : 'No healing sessions recorded yet.'}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function OperatorLoginPage() {
  const [password, setPassword] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    apiRequest('/auth/session', { signal: controller.signal })
      .then(() => window.location.replace('/operator'))
      .catch(() => {})
    return () => controller.abort()
  }, [])

  const submitLogin = async (event) => {
    event.preventDefault()
    setIsSubmitting(true)
    setErrorMessage('')

    try {
      await apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ password })
      })
      window.location.replace('/operator')
    } catch (error) {
      setErrorMessage(error.message || 'Unable to sign in.')
      setIsSubmitting(false)
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel" aria-labelledby="operator-login-title">
        <a className="back-link" href="/">← Overview</a>
        <div className="auth-kicker">
          <span className="status-dot healthy"></span>
          Restricted access
        </div>
        <h1 id="operator-login-title" className="auth-title">Operator login</h1>
        <p className="auth-copy">
          Sign in to view live upstream health, incident history, and gateway operations.
        </p>

        <form className="auth-form" onSubmit={submitLogin}>
          <label className="auth-label" htmlFor="operator-password">Operator password</label>
          <input
            id="operator-password"
            className="auth-input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={event => setPassword(event.target.value)}
            disabled={isSubmitting}
            required
            autoFocus
          />
          {errorMessage && <div className="auth-error" role="alert">{errorMessage}</div>}
          <button className="auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Signing in…' : 'Enter operator view'}
          </button>
        </form>

        <p className="auth-footnote">
          Looking for the portfolio walkthrough? <a href="/dashboard">Open the public demo</a>.
        </p>
      </section>
    </main>
  )
}

function App() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  if (path === '/dashboard') return <DashboardPage />
  if (path === '/operator/login') return <OperatorLoginPage />
  if (path === '/operator') return <DashboardPage operatorMode />
  return <LandingPage />
}

export default App
