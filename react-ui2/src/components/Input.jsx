import './Input.css'

/**
 * Reusable Input Component
 */
export function Input({ 
  label,
  type = 'text',
  value,
  onChange,
  placeholder,
  disabled = false,
  error,
  className = '',
  ...props 
}) {
  return (
    <div className={`input-wrapper ${className}`}>
      {label && <label className="input-label">{label}</label>}
      <input
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        disabled={disabled}
        className={`input ${error ? 'input-error' : ''}`}
        {...props}
      />
      {error && <span className="input-error-text">{error}</span>}
    </div>
  )
}

/**
 * Reusable Select Component
 */
export function Select({ 
  label,
  value,
  onChange,
  options = [],
  placeholder = 'Seleccionar...',
  disabled = false,
  className = '',
  ...props 
}) {
  return (
    <div className={`input-wrapper ${className}`}>
      {label && <label className="input-label">{label}</label>}
      <select
        value={value}
        onChange={onChange}
        disabled={disabled}
        className="input"
        {...props}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}

/**
 * Reusable Checkbox Component
 */
export function Checkbox({ 
  label,
  checked,
  onChange,
  disabled = false,
  className = '',
  ...props 
}) {
  return (
    <label className={`checkbox-wrapper ${className}`}>
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        className="checkbox"
        {...props}
      />
      <span className="checkbox-label">{label}</span>
    </label>
  )
}
