import { useState } from 'react'
import { useFetch } from '../hooks'
import { apiService } from '../services/api'
import { Input, Select, Button, Card, Loader, Badge } from '../components'
import { formatDateTimeFull, getChatTypeName } from '../utils/helpers'
import './Chats.css'

/**
 * Chats View - List and manage chats
 */
export function Chats({ onSelectChat, selectedChat }) {
  const [filters, setFilters] = useState({
    account: '',
    chat_id: '',
    search: '',
    chat_type: '',
    limit: 50
  })

  const { data: chats, loading, refetch } = useFetch(
    () => apiService.chats.list(filters),
    [filters]
  )

  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }))
  }

  const handleToggleMedia = async (chat, e) => {
    e.stopPropagation()
    try {
      await apiService.chats.updateSettings(
        chat.chat_id,
        chat.account_phone,
        { media_download_enabled: !chat.media_download_enabled }
      )
      refetch()
    } catch (error) {
      console.error('Error updating chat settings:', error)
    }
  }

  const copyToClipboard = async (text) => {
    const value = String(text ?? '')
    if (!value) return
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(value)
        return
      }
    } catch {
      // fallback below
    }

    const textarea = document.createElement('textarea')
    textarea.value = value
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
    } finally {
      document.body.removeChild(textarea)
    }
  }

  const getLastMessageDateValue = (chat) => {
    return formatDateTimeFull(chat?.last_msg)
  }

  return (
    <div className="chats-view">
      {/* Filters */}
      <Card className="filters-card">
        <div className="filters-grid">
          <Input
            placeholder="Cuenta asociada (+34...)"
            value={filters.account}
            onChange={(e) => handleFilterChange('account', e.target.value)}
          />
          <Input
            placeholder="ID chat"
            value={filters.chat_id}
            onChange={(e) => {
              const cleaned = e.target.value.replace(/[^0-9-]/g, '')
              handleFilterChange('chat_id', cleaned === '-' ? '' : cleaned)
            }}
          />
          <Input
            placeholder="Buscar chat..."
            value={filters.search}
            onChange={(e) => handleFilterChange('search', e.target.value)}
          />
          <Select
            value={filters.chat_type}
            onChange={(e) => handleFilterChange('chat_type', e.target.value)}
            options={[
              { value: 'user', label: 'Usuario' },
              { value: 'bot', label: 'Bot' },
              { value: 'private', label: 'Privado' },
              { value: 'group', label: 'Grupo' },
              { value: 'supergroup', label: 'Supergrupo' },
              { value: 'channel', label: 'Canal' }
            ]}
            placeholder="Tipo"
          />
        </div>
        <div className="filters-actions">
          <Button onClick={refetch} size="small">↻</Button>
        </div>
      </Card>

      {/* Chats List */}
      {loading ? (
        <Loader text="Cargando..." />
      ) : (
        <div className="chats-list">
          {chats && chats.length > 0 ? (
            chats.map((chat) => (
              <div
                key={`${chat.chat_id}-${chat.account_phone}`}
                className={`chat-item ${selectedChat?.chat_id === chat.chat_id ? 'active' : ''}`}
                onClick={() => onSelectChat(chat)}
              >
                <div className="chat-item-header">
                  <h3
                    className="chat-item-title chat-copy"
                    title="Click para copiar título"
                    onClick={() => copyToClipboard(chat.title || 'Sin nombre')}
                  >
                    {chat.title || 'Sin nombre'}
                  </h3>
                  <Badge variant="info" className="chat-item-type">
                    {getChatTypeName(chat.chat_type)}
                  </Badge>
                </div>
                <div className="chat-item-meta">
                  <div className="chat-item-details">
                    <div className="chat-meta-badges">
                      <span
                        className="chat-copy"
                        title="Click para copiar ID"
                        onClick={() => copyToClipboard(chat.chat_id)}
                      >
                        <Badge variant="secondary">Chat ID: {chat.chat_id}</Badge>
                      </span>

                      <span
                        className="chat-copy"
                        title="Click para copiar cuenta"
                        onClick={() => copyToClipboard(chat.account_phone || 'N/A')}
                      >
                        <Badge variant="secondary">Cuenta: {chat.account_phone || 'N/A'}</Badge>
                      </span>
                    </div>

                    <div className="chat-meta-badges chat-meta-badges-bottom">
                      <span
                        className="chat-copy"
                        title="Click para copiar último mensaje"
                        onClick={() => copyToClipboard(getLastMessageDateValue(chat))}
                      >
                        <Badge variant="secondary">Último: {getLastMessageDateValue(chat)}</Badge>
                      </span>
                    </div>
                  </div>
                  <Button
                    size="small"
                    variant={chat.media_download_enabled ? 'primary' : 'secondary'}
                    onClick={(e) => handleToggleMedia(chat, e)}
                    title={chat.media_download_enabled ? 'Media: activada' : 'Media: desactivada'}
                  >
                    {chat.media_download_enabled ? '📥' : '🚫'}
                  </Button>
                </div>
              </div>
            ))
          ) : (
            <div className="empty-state">
              <p>No hay chats</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
