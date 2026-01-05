import { useState } from 'react'
import { useFetch, useAutoRefresh } from '../hooks'
import { apiService } from '../services/api'
import { Loader, Badge, StatusBadge } from '../components'
import { formatDate, formatNumber, getStatusColor } from '../utils/helpers'
import './Downloads.css'

/**
 * Downloads View - Monitor download queue
 */
export function Downloads() {
  const [autoRefresh, setAutoRefresh] = useState(true)

  const { data: downloads, loading, refetch } = useFetch(
    () => apiService.downloads.list({ limit: 20 }),
    []
  )

  const { data: queueStats, refetch: refetchStats } = useFetch(
    () => apiService.getQueueStats(),
    []
  )

  useAutoRefresh(refetch, 5000, autoRefresh)

  // Mantener stats y lista sincronizados
  useAutoRefresh(refetchStats, 5000, autoRefresh)

  const stats = queueStats?.stats || []
  const pendingTotal = queueStats?.pending_total ?? 0

  const getStatValue = (status) => {
    const stat = stats.find(s => s.status === status)
    return stat ? stat.total : 0
  }

  const pendingEffective = getStatValue('pending')
  const inProgressCount = getStatValue('in_progress')
  const doneCount = getStatValue('done')
  const failedCount = getStatValue('failed')

  const visibleDownloads = (downloads || []).slice(0, 20)

  return (
    <div className="downloads-view">
      {/* Header */}
      <div className="downloads-header">
        <div className="downloads-stats">
          <div className="stat-item">
            <span className="stat-value">{formatNumber(inProgressCount)}</span>
            <span className="stat-label">En progreso</span>
          </div>
          <div className="stat-item">
            <span className="stat-value">{formatNumber(pendingTotal)}</span>
            <span className="stat-label">Pendientes (total)</span>
          </div>
          <div className="stat-item">
            <span className="stat-value">{formatNumber(pendingEffective)}</span>
            <span className="stat-label">Pendientes (efectivos)</span>
          </div>
          <div className="stat-item">
            <span className="stat-value">{formatNumber(doneCount)}</span>
            <span className="stat-label">Completadas</span>
          </div>
          <div className="stat-item">
            <span className="stat-value">{formatNumber(failedCount)}</span>
            <span className="stat-label">Fallidas</span>
          </div>
        </div>
        <label className="auto-refresh">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          <span>Auto-refresh</span>
        </label>
      </div>

      {/* Downloads List */}
      {loading && !downloads ? (
        <Loader text="Cargando..." />
      ) : (
        <div className="downloads-list">
          {visibleDownloads.length > 0 ? (
            visibleDownloads.map((download) => (
              <div key={download.id ?? `${download.chat_id}:${download.msg_id}:${download.updated_at ?? ''}`} className="download-item">
                <div className="download-header">
                  <StatusBadge
                    status={download.status}
                    color={getStatusColor(download.status)}
                  />
                  <span className="download-date">
                    {formatDate(download.updated_at)}
                  </span>
                </div>

                <div className="download-meta">
                  <div className="download-meta-row">
                    <Badge variant="secondary">Cuenta: {download.account_phone || 'N/A'}</Badge>
                    <Badge variant="secondary">Chat ID: {download.chat_id ?? 'N/A'}</Badge>
                  </div>

                  <div className="download-meta-row">
                    <Badge variant="secondary">Msg ID: {download.msg_id ?? 'N/A'}</Badge>
                    <Badge variant="secondary">Sender ID: {download.sender_id ?? 'N/A'}</Badge>
                  </div>

                  <div className="download-meta-row">
                    <Badge variant="secondary">Tipo: {download.media_type || 'N/A'}</Badge>
                    <Badge variant="secondary">Archivo: {download.file_name || 'N/A'}</Badge>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="empty-state">
              <p>No hay descargas</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
