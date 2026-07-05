import React, { useEffect, useState } from 'react'
import axios from 'axios'
import './index.css'

const API_URL = 'http://localhost:8000'

function App() {
  const [gatewayStatus, setGatewayStatus] = useState({})
  const [auditSessions, setAuditSessions] = useState([])

  const fetchData = async () => {
    try {
      const [statusRes, auditRes] = await Promise.all([
        axios.get(`${API_URL}/gateway/health-status`),
        axios.get(`${API_URL}/audit/sessions`)
      ])
      setGatewayStatus(statusRes.data)
      setAuditSessions(auditRes.data)
    } catch (error) {
      console.error('Error fetching data:', error)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [])

  const formatDate = (dateString) => {
    if (!dateString) return '-'
    const date = new Date(dateString)
    
    // Formatting: MM/DD, HH:MM:SS
    const options = { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }
    return date.toLocaleString(undefined, options)
  }

  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <h1 className="dashboard-title">Gateway Monitor</h1>
        <div className="dashboard-subtitle">Self-healing infrastructure control plane</div>
      </header>

      <section>
        <h2 className="section-title">Upstreams</h2>
        <div className="upstreams-list">
          {Object.entries(gatewayStatus).map(([url, data]) => (
            <div className="upstream-item" key={url}>
              <div className="upstream-url">{url}</div>
              
              <div className="status-label">
                <div className={`status-dot ${data.is_healthy ? 'healthy' : 'unhealthy'}`}></div>
                {data.is_healthy ? 'Healthy' : 'Unhealthy'}
              </div>
              
              <div className="metric-group">
                <span className="metric-label">Circuit</span>
                <span className={`metric-value cb-${data.circuit_state.toLowerCase()}`}>
                  {data.circuit_state}
                </span>
              </div>
              
              <div className="metric-group">
                <span className="metric-label">Failures</span>
                <span className="metric-value">{data.failure_count}</span>
              </div>
            </div>
          ))}
          {Object.keys(gatewayStatus).length === 0 && (
            <div className="empty-state">No upstreams configured.</div>
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
              <div className="reason-text" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: '1.4' }}>
                {session.reason || 'Max iterations reached (No reason provided by agent)'}
              </div>
              <div className="tag-list">
                {session.actions_taken && session.actions_taken.length > 0 ? (
                  session.actions_taken.map((action, idx) => (
                    <span key={idx} className="action-tag">{action}</span>
                  ))
                ) : (
                  <span style={{ color: 'var(--text-secondary)' }}>-</span>
                )}
              </div>
            </div>
          ))}
          {auditSessions.length === 0 && (
            <div className="empty-state">No healing sessions recorded yet.</div>
          )}
        </div>
      </section>
    </div>
  )
}

export default App
