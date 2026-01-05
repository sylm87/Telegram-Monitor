import { useState } from 'react'
import { useFetch, useAutoRefresh } from '../hooks'
import { apiService } from '../services/api'
import { StatCard, Loader } from '../components'
import { formatNumber } from '../utils/helpers'
import './Dashboard.css'

/**
 * Dashboard View - Statistics and Overview
 */
export function Dashboard() {
  const [autoRefresh, setAutoRefresh] = useState(true)
  
  const { data: queueStats, loading, refetch } = useFetch(
    () => apiService.getQueueStats(),
    []
  )

  // Auto-refresh every 5 seconds
  useAutoRefresh(refetch, 5000, autoRefresh)

  const stats = queueStats?.stats || []
  const aging = queueStats?.aging || []

  const getStatValue = (status) => {
    const stat = stats.find(s => s.status === status)
    return stat ? formatNumber(stat.total) : '0'
  }

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h1 className="dashboard-title">
          <span className="terminal-prompt">$</span> Dashboard
        </h1>
        <div className="dashboard-controls">
          <label className="auto-refresh-toggle">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            <span>Auto-refresh</span>
          </label>
        </div>
      </div>

      {loading && !queueStats ? (
        <Loader text="Cargando estadísticas..." />
      ) : (
        <>
          {/* Queue Statistics */}
          <section className="dashboard-section">
            <h2 className="section-title">Estado de la Cola</h2>
            <div className="stats-grid">
              <StatCard
                title="Pendientes (efectivos)"
                value={getStatValue('pending')}
                icon="⏳"
              />
              <StatCard
                title="En Progreso"
                value={getStatValue('in_progress')}
                icon="⚙️"
              />
              <StatCard
                title="Completados"
                value={getStatValue('done')}
                icon="✓"
              />
              <StatCard
                title="Fallidos"
                value={getStatValue('failed')}
                icon="✗"
              />
            </div>
          </section>

          {/* Aging Messages */}
          {aging && aging.length > 0 && (
            <section className="dashboard-section">
              <h2 className="section-title">Mensajes Antiguos Pendientes</h2>
              <div className="aging-grid">
                {aging.map((item, index) => (
                  <div key={index} className="aging-item">
                    <div className="aging-range">{item.age_range}</div>
                    <div className="aging-count">{formatNumber(item.count)}</div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* System Info */}
          <section className="dashboard-section">
            <h2 className="section-title">Información del Sistema</h2>
            <div className="system-info">
              <div className="info-item">
                <span className="info-label">Total en Cola:</span>
                <span className="info-value">
                  {formatNumber(stats.reduce((sum, s) => sum + s.total, 0))}
                </span>
              </div>
              <div className="info-item">
                <span className="info-label">Última actualización:</span>
                <span className="info-value">{new Date().toLocaleTimeString()}</span>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
