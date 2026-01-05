import { useState } from 'react'
import { apiService } from '../services/api'
import { Input, Button, Checkbox, Loader, Badge } from '../components'
import { formatDate } from '../utils/helpers'
import './Search.css'

/**
 * Search View - Search messages across all chats
 */
export function Search({ onSelectChat }) {
  const PAGE_SIZE = 1000

  const [form, setForm] = useState({
    q: '',
    account: '',
    chat_id: '',
    sender_id: '',
    sender_username: '',
    chat_type: '',
    media_type: '',
    date_from: '',
    date_to: '',
    media_only: false
  })

  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)

  const handleChange = (key, value) => {
    setForm(prev => ({ ...prev, [key]: value }))
  }

  const buildFilters = () =>
    Object.fromEntries(
      Object.entries(form).filter(([_, value]) => {
        if (typeof value === 'boolean') return value
        return value !== '' && value !== null && value !== undefined
      })
    )

  const handleSearch = async (e) => {
    e.preventDefault()
    
    if (!form.q.trim() && !form.account && !form.chat_id && !form.sender_id && !form.sender_username) {
      return
    }

    setLoading(true)
    setLoadingMore(false)
    setResults([])
    setOffset(0)
    setHasMore(false)
    
    try {
      const filters = buildFilters()
      const data = await apiService.search.messages({
        ...filters,
        limit: PAGE_SIZE,
        offset: 0,
      })

      setResults(Array.isArray(data) ? data : [])
      setHasMore(Array.isArray(data) && data.length === PAGE_SIZE)
      setOffset(PAGE_SIZE)
    } catch (error) {
      console.error('Search error:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleLoadMore = async () => {
    if (loading || loadingMore || !hasMore) return

    setLoadingMore(true)
    try {
      const filters = buildFilters()
      const data = await apiService.search.messages({
        ...filters,
        limit: PAGE_SIZE,
        offset,
      })

      const next = Array.isArray(data) ? data : []

      setResults(prev => {
        const seen = new Set(prev.map(m => `${m.account_phone}|${m.chat_id}|${m.msg_id}`))
        const toAdd = next.filter(m => {
          const key = `${m.account_phone}|${m.chat_id}|${m.msg_id}`
          if (seen.has(key)) return false
          seen.add(key)
          return true
        })
        return [...prev, ...toAdd]
      })

      setHasMore(next.length === PAGE_SIZE)
      setOffset(prev => prev + PAGE_SIZE)
    } catch (error) {
      console.error('Load more error:', error)
    } finally {
      setLoadingMore(false)
    }
  }

  const handleViewInContext = (message, e) => {
    e.stopPropagation()
    if (onSelectChat) {
      // Crear objeto de chat con el msg_id para scroll directo
      const chat = {
        chat_id: message.chat_id,
        title: message.chat_title || `Chat ${message.chat_id}`,
        account_phone: message.account_phone,
        chat_type: message.chat_type || 'unknown',
        scrollToMsgId: message.msg_id // Parámetro especial para scroll
      }
      onSelectChat(chat)
    }
  }

  return (
    <div className="search-view">
      {/* Search Form */}
      <form onSubmit={handleSearch} className="search-form">
        <div className="search-main">
          <Input
            placeholder="Buscar en texto de mensajes..."
            value={form.q}
            onChange={(e) => handleChange('q', e.target.value)}
          />
          <Button 
            type="button" 
            variant="secondary"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? '▼' : '▶'} Filtros avanzados
          </Button>
        </div>

        {/* Advanced Filters */}
        {showAdvanced && (
          <div className="search-advanced">
            <div className="filter-row">
              <Input
                label="Cuenta (teléfono)"
                placeholder="+34671181630"
                value={form.account}
                onChange={(e) => handleChange('account', e.target.value)}
              />
              <Input
                label="ID Chat"
                placeholder="-1001089883232"
                value={form.chat_id}
                onChange={(e) => handleChange('chat_id', e.target.value)}
              />
            </div>

            <div className="filter-row">
              <Input
                label="ID Usuario"
                placeholder="665766277"
                value={form.sender_id}
                onChange={(e) => handleChange('sender_id', e.target.value)}
              />
              <Input
                label="Username"
                placeholder="kaihui03"
                value={form.sender_username}
                onChange={(e) => handleChange('sender_username', e.target.value)}
              />
            </div>

            <div className="filter-row">
              <select 
                className="filter-select"
                value={form.chat_type}
                onChange={(e) => handleChange('chat_type', e.target.value)}
              >
                <option value="">Todos los tipos de chat</option>
                <option value="channel">Canal</option>
                <option value="group">Grupo</option>
                <option value="supergroup">Supergrupo</option>
                <option value="private">Privado</option>
              </select>

              <select 
                className="filter-select"
                value={form.media_type}
                onChange={(e) => handleChange('media_type', e.target.value)}
              >
                <option value="">Todos los tipos de media</option>
                <option value="photo">Foto</option>
                <option value="video">Video</option>
                <option value="document">Documento</option>
                <option value="audio">Audio</option>
                <option value="voice">Voz</option>
              </select>
            </div>

            <div className="filter-row">
              <Input
                label="Desde"
                type="date"
                value={form.date_from}
                onChange={(e) => handleChange('date_from', e.target.value)}
              />
              <Input
                label="Hasta"
                type="date"
                value={form.date_to}
                onChange={(e) => handleChange('date_to', e.target.value)}
              />
            </div>

            <div className="search-options">
              <Checkbox
                label="Solo mensajes con media"
                checked={form.media_only}
                onChange={(e) => handleChange('media_only', e.target.checked)}
              />
            </div>
          </div>
        )}

        <Button type="submit" loading={loading}>
          🔍 Buscar
        </Button>
      </form>

      {/* Search Results */}
      {loading && results.length === 0 ? (
        <Loader text="Buscando..." />
      ) : (
        <div className="search-results">
          {results.length > 0 ? (
            <>
              <div className="results-count">
                {results.length} resultado{results.length !== 1 ? 's' : ''}
              </div>
              <div className="results-list">
                {results.map((message, index) => (
                  <div 
                    key={index} 
                    className="result-item"
                  >
                    <div className="result-header">
                      <div className="result-info">
                        <div className="result-main-info">
                          {message.chat_type && (
                            <Badge variant="primary" className="result-chat-type">
                              {message.chat_type}
                            </Badge>
                          )}
                          <span className="result-sender-type">
                            {message.sender_is_bot ? '🤖 Bot' : '👤 User'}
                          </span>
                          {message.sender_id && (
                            <span className="result-sender-id">
                              ID: {message.sender_id}
                            </span>
                          )}
                          {message.sender_username && (
                            <span className="result-sender-username">
                              @{message.sender_username}
                            </span>
                          )}
                          {message.sender_first_name && (
                            <span className="result-sender-name">
                              {message.sender_first_name} {message.sender_last_name || ''}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="result-actions">
                        <span className="result-date">{formatDate(message.created_at)}</span>
                        <Button
                          variant="secondary"
                          size="small"
                          onClick={(e) => handleViewInContext(message, e)}
                          title="Ver en contexto del chat"
                        >
                          👁️
                        </Button>
                      </div>
                    </div>

                    <div className="result-meta">
                      <Badge variant="secondary">Msg ID: {message.msg_id}</Badge>
                      {message.chat_title && (
                        <Badge variant="secondary">Chat: {message.chat_title}</Badge>
                      )}
                      {message.chat_id && (
                        <Badge variant="secondary">Chat ID: {message.chat_id}</Badge>
                      )}
                      {message.media_type && (
                        <Badge variant="secondary">{message.media_type}</Badge>
                      )}
                    </div>

                    {message.text && (
                      <div className="result-text">
                        {highlightSearchTerm(message.text, form.q)}
                      </div>
                    )}

                    {message.media_file_path && (
                      <div className="result-media-info">
                        📎 {message.media_file_path.split('/').pop()}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {hasMore && (
                <div className="results-load-more">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={handleLoadMore}
                    loading={loadingMore}
                  >
                    Cargar más ({PAGE_SIZE})
                  </Button>
                </div>
              )}
            </>
          ) : form.q || form.account || form.chat_id || form.sender_id ? (
            <div className="empty-state">
              <p>No se encontraron resultados</p>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

function highlightSearchTerm(text, searchTerm) {
  if (!searchTerm || !text) return text

  const parts = text.split(new RegExp(`(${searchTerm})`, 'gi'))
  
  return (
    <span>
      {parts.map((part, i) => 
        part.toLowerCase() === searchTerm.toLowerCase() ? (
          <mark key={i} className="highlight">{part}</mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </span>
  )
}
