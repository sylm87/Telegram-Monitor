import { useState } from 'react'
import { Sidebar } from './components/Sidebar'
import { ChatViewer } from './components/ChatViewer'
import './App.css'

/**
 * Main App Component
 */
function App() {
  const [selectedChat, setSelectedChat] = useState(null)

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <div className="app-logo">
          <span className="logo-bracket">{'['}</span>
          <span className="logo-text">TELEGRAM MONITOR</span>
          <span className="logo-bracket">{']'}</span>
        </div>
        <div className="header-status">
          <span className="terminal-prompt">$</span>
          <span className="status-online">ONLINE</span>
        </div>
      </header>

      {/* Main Split Layout */}
      <main className="app-main">
        <div className="app-sidebar">
          <Sidebar 
            selectedChat={selectedChat}
            onSelectChat={setSelectedChat}
          />
        </div>
        <div className="app-viewer">
          <ChatViewer 
            chat={selectedChat}
            onClose={() => setSelectedChat(null)}
          />
        </div>
      </main>
    </div>
  )
}

export default App
