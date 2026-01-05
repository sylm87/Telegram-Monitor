import './Loader.css'

/**
 * Loading Spinner Component
 */
export function Loader({ size = 'medium', text = 'Cargando...' }) {
  return (
    <div className="loader-container">
      <div className={`loader loader-${size}`}>
        <div className="loader-spinner"></div>
      </div>
      {text && <div className="loader-text">{text}</div>}
    </div>
  )
}

/**
 * Inline Loader
 */
export function InlineLoader() {
  return <span className="inline-loader">⟳</span>
}
