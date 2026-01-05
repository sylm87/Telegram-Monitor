import { useState } from 'react'
import { Chats } from '../views/Chats'
import { Search } from '../views/Search'
import { Downloads } from '../views/Downloads'
import './Sidebar.css'

/**
 * Sidebar Component with Tabs
 */
export function Sidebar({ selectedChat, onSelectChat }) {
  const [activeTab, setActiveTab] = useState('chats')

  const renderTabContent = () => {
    switch (activeTab) {
      case 'chats':
        return <Chats onSelectChat={onSelectChat} selectedChat={selectedChat} />
      case 'search':
        return <Search onSelectChat={onSelectChat} />
      case 'downloads':
        return <Downloads />
      default:
        return <Chats onSelectChat={onSelectChat} selectedChat={selectedChat} />
    }
  }

  return (
    <div className="sidebar">
      {/* Tabs */}
      <div className="sidebar-tabs">
        <button
          className={`sidebar-tab ${activeTab === 'chats' ? 'active' : ''}`}
          onClick={() => setActiveTab('chats')}
        >
          <span className="tab-icon">💬</span>
          Chats
        </button>
        <button
          className={`sidebar-tab ${activeTab === 'search' ? 'active' : ''}`}
          onClick={() => setActiveTab('search')}
        >
          <span className="tab-icon">🔍</span>
          Búsqueda
        </button>
        <button
          className={`sidebar-tab ${activeTab === 'downloads' ? 'active' : ''}`}
          onClick={() => setActiveTab('downloads')}
        >
          <span className="tab-icon">⬇️</span>
          Descargas
        </button>
      </div>

      {/* Tab Content with forced scroll */}
      <div className="sidebar-content-wrapper">
        <div className="sidebar-content">
          {renderTabContent()}
        </div>
      </div>
    </div>
  )
}
