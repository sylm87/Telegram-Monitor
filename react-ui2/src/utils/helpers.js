/**
 * Utility Functions
 */

/**
 * Format date/time
 */
export function formatDate(dateString) {
  if (!dateString) return 'N/A'

  const date = parseApiDate(dateString)
  if (!date) return 'N/A'
  const now = new Date()
  const diffInHours = (now - date) / (1000 * 60 * 60)
  
  if (diffInHours < 24) {
    return new Intl.DateTimeFormat(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  } else if (diffInHours < 24 * 7) {
    return new Intl.DateTimeFormat(undefined, {
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  } else {
    return new Intl.DateTimeFormat(undefined, {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    }).format(date)
  }
}

/**
 * Parse de fechas provenientes del backend.
 * - Si viene un timestamp tipo "YYYY-MM-DD HH:mm:ss" (sin zona), se asume UTC.
 * - Si viene en ISO con Z/offset, se respeta.
 * - Si viene numérico, se interpreta como segundos o milisegundos.
 */
export function parseApiDate(value) {
  if (value === null || value === undefined || value === '') return null

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }

  if (typeof value === 'number' && Number.isFinite(value)) {
    const ms = value > 1e12 ? value : value > 1e9 ? value * 1000 : value
    const date = new Date(ms)
    return Number.isNaN(date.getTime()) ? null : date
  }

  const text = String(value).trim()
  if (!text) return null

  if (/^\d+$/.test(text)) {
    const n = Number(text)
    if (!Number.isFinite(n)) return null
    const ms = n > 1e12 ? n : n > 1e9 ? n * 1000 : n
    const date = new Date(ms)
    return Number.isNaN(date.getTime()) ? null : date
  }

  const normalized = text.replace(' ', 'T')
  const hasTimezone = /[zZ]$|[+-]\d{2}:\d{2}$/.test(normalized)
  const looksLikeDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(normalized)
  const looksLikeDateTimeNoTz =
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?$/.test(normalized)

  const isoAssumingUtc =
    looksLikeDateOnly
      ? `${normalized}T00:00:00Z`
      : looksLikeDateTimeNoTz && !hasTimezone
        ? `${normalized}Z`
        : normalized

  const date = new Date(isoAssumingUtc)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDateTimeFull(value) {
  const date = parseApiDate(value)
  if (!date) return 'N/A'

  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

export function formatDateTimeDMYHMS(value) {
  const date = parseApiDate(value)
  if (!date) return 'N/A'

  const pad2 = (n) => String(n).padStart(2, '0')
  const dd = pad2(date.getDate())
  const mm = pad2(date.getMonth() + 1)
  const yyyy = String(date.getFullYear())
  const hh = pad2(date.getHours())
  const min = pad2(date.getMinutes())
  const ss = pad2(date.getSeconds())

  return `${dd}/${mm}/${yyyy} ${hh}:${min}:${ss}`
}

/**
 * Format file size
 */
export function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`
}

/**
 * Format number with thousand separators
 */
export function formatNumber(num) {
  if (num === null || num === undefined) return '0'
  return num.toLocaleString()
}

/**
 * Debounce function
 */
export function debounce(func, wait) {
  let timeout
  
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout)
      func(...args)
    }
    
    clearTimeout(timeout)
    timeout = setTimeout(later, wait)
  }
}

/**
 * Truncate text
 */
export function truncate(text, maxLength = 50) {
  if (!text || text.length <= maxLength) return text
  return `${text.substring(0, maxLength)}...`
}

/**
 * Get chat type display name
 */
export function getChatTypeName(type) {
  const types = {
    private: 'Privado',
    user: 'Usuario',
    bot: 'Bot',
    group: 'Grupo',
    supergroup: 'Supergrupo',
    channel: 'Canal',
  }
  return types[type] || type
}

/**
 * Get status badge color
 */
export function getStatusColor(status) {
  const colors = {
    pending: '#00ff00',
    in_progress: '#00ffff',
    completed: '#00ff00',
    failed: '#ff0000',
    error: '#ff0000',
  }
  return colors[status] || '#00ff00'
}

/**
 * Class names helper
 */
export function cn(...classes) {
  return classes.filter(Boolean).join(' ')
}
