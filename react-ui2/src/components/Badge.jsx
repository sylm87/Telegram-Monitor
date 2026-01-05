import './Badge.css'

/**
 * Badge Component
 */
export function Badge({ children, variant = 'primary', className = '' }) {
  return (
    <span className={`badge badge-${variant} ${className}`}>
      {children}
    </span>
  )
}

/**
 * Status Badge with color indicator
 */
export function StatusBadge({ status, color }) {
  return (
    <span className="status-badge">
      <span className="status-indicator" style={{ backgroundColor: color }}></span>
      {status}
    </span>
  )
}
