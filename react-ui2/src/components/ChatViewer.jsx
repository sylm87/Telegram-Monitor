import { ChatMessages } from '../views/ChatMessages'
import { Button, Badge } from './index'
import './ChatViewer.css'

/**
 * Chat Viewer Component with fixed header
 */
export function ChatViewer({ chat, onClose }) {
  if (!chat) {
    return (
      <div className="chat-viewer-wrapper">
        <div className="chat-viewer-empty">
          <div className="empty-icon">💬</div>
          <div className="empty-text">Selecciona un chat para ver los mensajes</div>
          <div className="empty-hint">
            <span className="terminal-prompt">$</span> 
            Usa la barra lateral para navegar
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-viewer-wrapper">
      {/* Fixed Header */}
      <div className="chat-viewer-header">
        <Button variant="secondary" onClick={onClose} size="small">
          ← Volver
        </Button>
        <div className="chat-viewer-info">
          <h2 className="chat-viewer-title">{chat.title || 'Sin nombre'}</h2>
          <div className="chat-viewer-meta">
            <Badge variant="info">ID: {chat.chat_id}</Badge>
            <Badge variant="secondary">{chat.chat_type}</Badge>
            {chat.account_phone && (
              <Badge variant="success">Línea: {chat.account_phone}</Badge>
            )}
          </div>
        </div>
      </div>

      {/* Messages Container */}
      <div className="chat-viewer-content">
        <ChatMessages key={chat.chat_id} chat={chat} />
      </div>
    </div>
  )
}
