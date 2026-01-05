import './Card.css'

/**
 * Reusable Card Component
 */
export function Card({ children, className = '', onClick, hoverable = false }) {
  return (
    <div 
      className={`card ${hoverable ? 'card-hoverable' : ''} ${onClick ? 'card-clickable' : ''} ${className}`}
      onClick={onClick}
    >
      {children}
    </div>
  )
}

/**
 * Card Header
 */
export function CardHeader({ children, className = '' }) {
  return <div className={`card-header ${className}`}>{children}</div>
}

/**
 * Card Body
 */
export function CardBody({ children, className = '' }) {
  return <div className={`card-body ${className}`}>{children}</div>
}

/**
 * Card Footer
 */
export function CardFooter({ children, className = '' }) {
  return <div className={`card-footer ${className}`}>{children}</div>
}

/**
 * Stat Card Component
 */
export function StatCard({ title, value, subtitle, icon }) {
  return (
    <Card className="stat-card">
      <div className="stat-card-content">
        {icon && <div className="stat-card-icon">{icon}</div>}
        <div className="stat-card-info">
          <div className="stat-card-title">{title}</div>
          <div className="stat-card-value">{value}</div>
          {subtitle && <div className="stat-card-subtitle">{subtitle}</div>}
        </div>
      </div>
    </Card>
  )
}
