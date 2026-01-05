import './Button.css'

/**
 * Reusable Button Component
 */
export function Button({ 
  children, 
  variant = 'primary', 
  size = 'medium',
  disabled = false,
  loading = false,
  onClick,
  type = 'button',
  className = '',
  ...props 
}) {
  return (
    <button
      type={type}
      className={`btn btn-${variant} btn-${size} ${disabled || loading ? 'btn-disabled' : ''} ${className}`}
      disabled={disabled || loading}
      onClick={onClick}
      {...props}
    >
      {loading ? (
        <span className="btn-loader">⟳</span>
      ) : (
        children
      )}
    </button>
  )
}
