import React, { useEffect, useState } from 'react'
import axios from 'axios'
import './index.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
const REFRESH_INTERVAL_MS = 5000
const TIME_ZONE = 'Asia/Kolkata'
const VAGUE_REASON_PHRASES = [
  'prevent cascading failures',
  'unhealthy service',
  'unhealthy upstream',
  'sudden unhealthiness'
]

const isVagueReason = (reason) => {
  if (!reason) return true
  const normalized = reason.toLowerCase()
  return VAGUE_REASON_PHRASES.some(phrase => normalized.includes(phrase))
}

const compactActionName = (action) => action
  .replace('get_upstream_state', 'checked')
  .replace('open_circuit', 'opened')
  .replace('close_circuit', 'closed')
  .replace('drain_upstream', 'drained')
  .replace('mark_resolved', 'resolved')

function App() {
  const [gatewayStatus, setGatewayStatus] = useState({})
  const [auditSessions, setAuditSessions] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [lastUpdated, setLastUpdated] = useState(null)

  const fetchData = async ({ signal, showLoading = false } = {}) => {
    if (showLoading) {
      setIsLoading(true)
    } else {
      setIsRefreshing(true)
    }

    try {
      const [statusRes, auditRes] = await Promise.all([
        axios.get(`${API_URL}/gateway/health-status`, { signal }),
        axios.get(`${API_URL}/audit/sessions`, { signal })
      ])
      setGatewayStatus(statusRes.data)
      setAuditSessions(auditRes.data)
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
      second: '2-digit',
      hour12: false,
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
    const actions = session.actions_taken || []
    const lastAction = actions[actions.length - 1]

    if (!isVagueReason(session.reason)) {
      return session.reason.split(' Agent note: ')[0]
    }

    if (session.status === 'resolved') {
      return lastAction
        ? `Handled by ${compactActionName(lastAction)}.`
        : 'Handled by healing workflow.'
    }

    if (lastAction) {
      return `Needs attention after ${compactActionName(lastAction)}.`
    }

    return 'No detailed reason recorded.'
  }

  const compactActions = (actions = []) => {
    const uniqueActions = [...new Set(actions)]
    return {
      visible: uniqueActions.slice(0, 2),
      hiddenCount: Math.max(uniqueActions.length - 2, 0),
      totalCount: actions.length
    }
  }

  const upstreamEntries = Object.entries(gatewayStatus)

  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <div>
          <h1 className="dashboard-title">Gateway Monitor</h1>
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
                  return (
                    <>
                      {actions.visible.map((action) => (
                        <span key={action} className="action-tag">
                          {compactActionName(action)}
                        </span>
                      ))}
                      {actions.hiddenCount > 0 && (
                        <span className="action-tag muted-tag">
                          +{actions.hiddenCount}
                        </span>
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

export default App
