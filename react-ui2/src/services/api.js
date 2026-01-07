/**
 * API Service Layer
 * Handles all HTTP communication with the backend
 */

function defaultApiBase() {
  if (typeof window !== 'undefined' && window.location) {
    return `${window.location.protocol}//${window.location.hostname}:8000`
  }
  return 'http://localhost:8000'
}

const API_BASE = import.meta.env.VITE_API_BASE || defaultApiBase()

/**
 * Generic HTTP wrapper with error handling
 */
async function http(path, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(errorText || response.statusText)
    }

    return await response.json()
  } catch (error) {
    console.error(`API Error [${path}]:`, error)
    throw error
  }
}

/**
 * Build query string from params object
 */
function buildQueryString(params = {}) {
  const searchParams = new URLSearchParams()
  
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.append(key, value)
    }
  })
  
  return searchParams.toString()
}

/**
 * API Client
 */
export const apiService = {
  /**
   * Get media file URL
   */
  getMediaUrl: (path) => `${API_BASE}/media?path=${encodeURIComponent(path)}`,

  /**
   * Queue Statistics
   */
  getQueueStats: () => http('/stats/queue'),

  /**
   * Chats
   */
  chats: {
    list: (filters = {}) => {
      const query = buildQueryString(filters)
      return http(`/chats?${query}`)
    },

    getMessages: (chatId, params = {}) => {
      const query = buildQueryString(params)
      return http(`/chats/${chatId}/messages?${query}`)
    },

    updateSettings: (chatId, account, settings) =>
      http(`/chats/${chatId}/settings?account=${encodeURIComponent(account)}`, {
        method: 'PATCH',
        body: JSON.stringify(settings),
      }),
  },

  /**
   * Downloads
   */
  downloads: {
    list: (params = {}) => {
      const query = buildQueryString(params)
      return http(`/downloads?${query}`)
    },
  },

  /**
   * Search
   */
  search: {
    messages: (params = {}) => {
      const query = buildQueryString(params)
      return http(`/search/messages?${query}`)
    },
  },
}

export default apiService
