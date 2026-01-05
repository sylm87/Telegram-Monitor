import { useState, useEffect, useLayoutEffect, useRef } from 'react'
import React from 'react'
import { apiService } from '../services/api'
import { Button, Card, Loader, Badge } from '../components'
import { formatDateTimeDMYHMS, formatFileSize } from '../utils/helpers'
import './ChatMessages.css'

/**
 * Chat Messages View with auto-scroll and infinite loading
 */
export function ChatMessages({ chat }) {
  const BOTTOM_STICKY_THRESHOLD_PX = 120
  const TOP_PREFETCH_VISIBLE_THRESHOLD = 10
  const MESSAGES_PAGE_LIMIT = 20
  const isSearchView = Boolean(chat?.scrollToMsgId)

  const scrollContainerToBottom = (behavior = 'auto') => {
    const container = messagesContainerRef.current
    if (!container) return

    // Preferimos scrollTop=scrollHeight (más determinista que scrollIntoView)
    if (behavior === 'auto') {
      container.scrollTop = container.scrollHeight
      return
    }

    // fallback suave para casos donde se quiera animación
    messagesEndRef.current?.scrollIntoView({ behavior })
  }

  const shouldRenderMessage = (message) => {
    if (!message) return false
    if (message.media_type === 'unrecoverable') return false

    const text = (message.text ?? '').toString().trim()
    const hasText = text.length > 0
    const hasMedia = Boolean(message.media_file_path)
    return hasText || hasMedia
  }

  // Estados separados para los parámetros de la API
  // Si viene desde búsqueda, NO inicializar beforeId, usaremos aroundId
  const [beforeId, setBeforeId] = useState(undefined)
  const [afterId, setAfterId] = useState(undefined)
  const [aroundId, setAroundId] = useState(chat.scrollToMsgId || undefined)
  const [refreshNonce, setRefreshNonce] = useState(0)
  
  // Estados para datos y UI
  const [messages, setMessages] = useState([])
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [allMessages, setAllMessages] = useState([])
  const [isAtBottom, setIsAtBottom] = useState(true)
  const [isAtTop, setIsAtTop] = useState(false)
  const [oldestMsgId, setOldestMsgId] = useState(null) // ID del mensaje más antiguo cargado
  const [newestMsgId, setNewestMsgId] = useState(null) // ID del mensaje más reciente cargado
  const [mediaViewer, setMediaViewer] = useState(null) // { url, mediaType, fileName }
  const [pagingEnabled, setPagingEnabled] = useState(false)
  
  // Refs
  const messagesEndRef = useRef(null)
  const messagesContainerRef = useRef(null)
  const isInitialLoad = useRef(!chat.scrollToMsgId) // Si hay scrollToMsgId, no es carga inicial
  const isAutoScrolling = useRef(false) // Flag para evitar conflictos durante auto-scroll
  const isLoadingOlder = useRef(false) // Flag: cargando histórico
  const anchorMessageId = useRef(null) // ID del mensaje ancla visual
  const scrollToTargetId = useRef(chat.scrollToMsgId || null) // Mensaje objetivo desde búsqueda
  const hasScrolledToTarget = useRef(false) // Ya hicimos scroll al target
  const hasLoadedAround = useRef(false) // Ya cargamos con around_id
  const isFocusingTarget = useRef(false) // Evita auto-scroll mientras enfocamos
  const stickToBottomRef = useRef(true) // "Pegado abajo" para autoscroll en updates
  const pendingAutoScrollToBottom = useRef(false) // Autoscroll pendiente tras render de nuevos mensajes
  const preLoadScrollHeightRef = useRef(null)
  const preLoadScrollTopRef = useRef(null)
  const forceScrollToBottomOnOpenRef = useRef(!chat.scrollToMsgId)
  const cancelOpenScrollRef = useRef(false)
  const openScrollCancelRef = useRef(null)
  const initialOpenTargetMsgIdRef = useRef(null)
  const pagingEnabledRef = useRef(false) // Hasta que el chat esté cargado y el scroll inicial esté asentado

  const enablePaging = () => {
    pagingEnabledRef.current = true
    setPagingEnabled(true)

    // Arrancar el after inmediatamente (sin esperar al siguiente intervalo)
    if (newestMsgId && !beforeId && !aroundId && !isLoadingOlder.current) {
      setAfterId(newestMsgId)
    }
    setRefreshNonce((n) => n + 1)
  }

  const startOpenScrollToBottom = (targetMsgId) => {
    const container = messagesContainerRef.current
    if (!container) return () => {}

    cancelOpenScrollRef.current = false
    const startedAt = performance.now()
    const maxMs = 8500
    const stableFramesRequired = 12
    const bottomAlignThresholdPx = 24
    let stableFrames = 0
    let rafId = 0

    const onUserIntent = () => {
      cancelOpenScrollRef.current = true
    }

    container.addEventListener('wheel', onUserIntent, { passive: true })
    container.addEventListener('touchstart', onUserIntent, { passive: true })
    container.addEventListener('pointerdown', onUserIntent, { passive: true })
    container.addEventListener('mousedown', onUserIntent, { passive: true })

    const stop = () => {
      container.removeEventListener('wheel', onUserIntent)
      container.removeEventListener('touchstart', onUserIntent)
      container.removeEventListener('pointerdown', onUserIntent)
      container.removeEventListener('mousedown', onUserIntent)
      if (rafId) cancelAnimationFrame(rafId)

      cancelOpenScrollRef.current = false
      forceScrollToBottomOnOpenRef.current = false
      isInitialLoad.current = false
      isAutoScrolling.current = false
      openScrollCancelRef.current = null

      // A partir de aquí ya permitimos before/after (auto-refresh y precarga de histórico)
      pagingEnabledRef.current = true
      setPagingEnabled(true)
    }

    const isTargetAlignedToBottom = (containerEl, targetEl) => {
      const cRect = containerEl.getBoundingClientRect()
      const tRect = targetEl.getBoundingClientRect()
      return Math.abs(cRect.bottom - tRect.bottom) <= bottomAlignThresholdPx
    }

    const tick = () => {
      const elapsed = performance.now() - startedAt
      if (elapsed > maxMs) {
        stop()
        return
      }

      // Si aparece un target (búsqueda) o el usuario interactúa, no pelear.
      if (cancelOpenScrollRef.current || scrollToTargetId.current || isFocusingTarget.current) {
        stop()
        return
      }

      const el = messagesContainerRef.current
      if (!el) {
        stop()
        return
      }

      const targetEl = targetMsgId ? document.getElementById(`msg-${targetMsgId}`) : null

      if (targetEl) {
        targetEl.scrollIntoView({ block: 'end', behavior: 'auto' })
        if (isTargetAlignedToBottom(el, targetEl)) {
          stableFrames += 1
        } else {
          stableFrames = 0
        }
      } else {
        // Fallback: bajar al fondo mientras el DOM se termina de montar
        scrollContainerToBottom('auto')
        stableFrames = 0
      }

      if (stableFrames >= stableFramesRequired) {
        setIsAtBottom(true)
        setIsAtTop(false)
        stickToBottomRef.current = true
        stop()
        return
      }

      rafId = requestAnimationFrame(tick)
    }

    rafId = requestAnimationFrame(() => {
      requestAnimationFrame(tick)
    })

    return stop
  }

  // Reset completo cuando cambia el chat (muy importante para que el 👁️ funcione
  // al navegar entre chats desde búsqueda).
  useEffect(() => {
    if (typeof openScrollCancelRef.current === 'function') {
      openScrollCancelRef.current()
    }

    // Bloquear before/after durante la carga inicial del nuevo chat
    pagingEnabledRef.current = false
    setPagingEnabled(false)

    // Reset de paginación/estado
    setBeforeId(undefined)
    setAfterId(undefined)
    setAroundId(chat.scrollToMsgId || undefined)
    setRefreshNonce(0)

    setMessages([])
    setAllMessages([])
    setOldestMsgId(null)
    setNewestMsgId(null)
    setHasMore(false)
    setIsAtBottom(true)
    setIsAtTop(false)

    // Reset de refs de control
    isInitialLoad.current = !chat.scrollToMsgId
    isAutoScrolling.current = false
    isLoadingOlder.current = false
    anchorMessageId.current = null
    stickToBottomRef.current = true
    pendingAutoScrollToBottom.current = false
    preLoadScrollHeightRef.current = null
    preLoadScrollTopRef.current = null

    // Si el chat se abre desde el panel (sin scrollToMsgId), siempre bajar al fondo.
    forceScrollToBottomOnOpenRef.current = !chat.scrollToMsgId
    cancelOpenScrollRef.current = false
    initialOpenTargetMsgIdRef.current = null

    scrollToTargetId.current = chat.scrollToMsgId || null
    hasScrolledToTarget.current = false
    hasLoadedAround.current = false
    isFocusingTarget.current = false
    setMediaViewer(null)
  }, [chat.chat_id, chat.account_phone, chat.scrollToMsgId])

  const openMediaViewer = (message) => {
    if (!message?.media_file_path) return
    const url = apiService.getMediaUrl(message.media_file_path)
    const fileName = message.media_file_path.split('/').pop()
    setMediaViewer({
      url,
      mediaType: message.media_type || '',
      fileName,
    })
  }

  // Fetch messages cuando cambian beforeId, afterId o aroundId
  useEffect(() => {
    const fetchMessages = async () => {
      // Si aroundId se limpia pero ya cargamos, no hacer nada
      if (!aroundId && hasLoadedAround.current && !beforeId && !afterId) {
        return
      }
      
      setLoading(true)
      try {
        const params = {
          account: chat.account_phone,
          limit: MESSAGES_PAGE_LIMIT
        }
        
        // Prioridad: around_id > before_id/after_id
        if (aroundId) {
          params.around_id = aroundId
          hasLoadedAround.current = true
        } else {
          // En carga inicial NO usar before/after hasta que el scroll inicial haya terminado.
          if (pagingEnabledRef.current) {
            if (beforeId) params.before_id = beforeId
            if (afterId) params.after_id = afterId
          }
        }
        
        const response = await apiService.chats.getMessages(chat.chat_id, params)
        setMessages(response.messages || [])
        setHasMore(response.more || false)
      } catch (error) {
        console.error('Error fetching messages:', error)
        setMessages([])
        setHasMore(false)
      } finally {
        setLoading(false)
      }
    }

    fetchMessages()
  }, [chat.chat_id, chat.account_phone, beforeId, afterId, aroundId, refreshNonce])
  
  // Prepare sorted messages before rendering
  const sortedMessages = React.useMemo(() => {
    if (messages.length === 0) return []
    // API returns DESC (newest first), we reverse to show chronological (oldest first)
    return [...messages].reverse()
  }, [messages])

  // Mensajes renderizables (el resto se usa para IDs/paginación, pero no se muestra)
  const visibleMessages = React.useMemo(() => {
    if (allMessages.length === 0) return []
    return allMessages.filter(shouldRenderMessage)
  }, [allMessages])

  // Update messages when new data arrives
  useEffect(() => {
    if (sortedMessages.length > 0) {
      if (isLoadingOlder.current) {
        // Guardar ancla ANTES de agregar mensajes antiguos
        const container = messagesContainerRef.current
        if (container && allMessages.length > 0) {
          // El primer mensaje VISIBLE es nuestro ancla (si no, el restore falla)
          const firstVisible = allMessages.find(shouldRenderMessage)
          anchorMessageId.current = (firstVisible || allMessages[0]).msg_id
        }
        
        // Loading older messages - prepend ONLY messages we don't have
        setAllMessages(prev => {
          const existingIds = new Set(prev.map(m => m.msg_id))
          const newOlderMessages = sortedMessages.filter(msg => !existingIds.has(msg.msg_id))
          
          const updated = [...newOlderMessages, ...prev]
          
          // Actualizar oldestMsgId con el mensaje MÁS ANTIGUO de TODOS los mensajes
          if (updated.length > 0) {
            setOldestMsgId(updated[0].msg_id)
          }
          
          return updated
        })
      } else if (aroundId) {
        // Carga con around_id - reemplazar todo y limpiar aroundId
        setAllMessages(sortedMessages)
        if (sortedMessages.length > 0) {
          setOldestMsgId(sortedMessages[0].msg_id)
          setNewestMsgId(sortedMessages[sortedMessages.length - 1].msg_id)
        }
        // Limpiar around_id DESPUÉS de procesar
        setAroundId(undefined)
      } else {
        // Initial load or refresh - filter only new messages if we already have some
        if (newestMsgId) {
          // Only add messages newer than what we have
          const newMessages = sortedMessages.filter(msg => msg.msg_id > newestMsgId)
          if (newMessages.length > 0) {
            // Si el usuario estaba pegado abajo ANTES del update, programar autoscroll post-render.
            // (Si el usuario se mueve arriba entre medias, se cancelará.)
            pendingAutoScrollToBottom.current = stickToBottomRef.current
            setAllMessages(prev => {
              const updated = [...prev, ...newMessages]
              // Actualizar newestMsgId con el mensaje MÁS NUEVO de TODOS los mensajes
              if (updated.length > 0) {
                setNewestMsgId(updated[updated.length - 1].msg_id)
              }
              return updated
            })
          }
        } else {
          // Initial load - set all messages and track IDs
          const initialVisible = sortedMessages.filter(shouldRenderMessage)
          const lastInitial = (initialVisible.length > 0
            ? initialVisible[initialVisible.length - 1]
            : sortedMessages[sortedMessages.length - 1])
          initialOpenTargetMsgIdRef.current = lastInitial?.msg_id ?? null

          setAllMessages(sortedMessages)
          if (sortedMessages.length > 0) {
            setOldestMsgId(sortedMessages[0].msg_id)
            setNewestMsgId(sortedMessages[sortedMessages.length - 1].msg_id)
          }
        }
      }
    }
  }, [sortedMessages, newestMsgId, allMessages, aroundId])

  // Al abrir un chat desde el panel: SIEMPRE empezar abajo (sin "flash" arriba).
  // useLayoutEffect corre antes del paint, así el primer frame ya sale abajo.
  // (Si viene desde búsqueda con scrollToMsgId, NO interferir.)
  useLayoutEffect(() => {
    if (!forceScrollToBottomOnOpenRef.current) return
    if (loading) return
    if (scrollToTargetId.current) return
    if (allMessages.length === 0) return

    isAutoScrolling.current = true
    stickToBottomRef.current = true
    const targetMsgId =
      initialOpenTargetMsgIdRef.current ||
      (visibleMessages[visibleMessages.length - 1]?.msg_id ?? allMessages[allMessages.length - 1]?.msg_id)

    // Paso síncrono: colocar ya el scroll abajo antes de pintar.
    // Si tenemos ancla de último msg, forzamos a ese elemento; si no, al fondo.
    const targetEl = targetMsgId ? document.getElementById(`msg-${targetMsgId}`) : null
    if (targetEl) {
      targetEl.scrollIntoView({ block: 'end', behavior: 'auto' })
    } else {
      scrollContainerToBottom('auto')
    }

    openScrollCancelRef.current = startOpenScrollToBottom(targetMsgId)

    return () => {
      if (typeof openScrollCancelRef.current === 'function') {
        openScrollCancelRef.current()
      }
    }
  }, [chat.chat_id, chat.account_phone, allMessages.length, loading])

  // Scroll al mensaje específico cuando viene desde búsqueda
  useEffect(() => {
    if (scrollToTargetId.current && !hasScrolledToTarget.current && allMessages.length > 0 && !loading) {
      // Usar el ancla HTML directamente
      const targetId = `msg-${scrollToTargetId.current}`
      
      console.log('🎯 Buscando mensaje objetivo:', {
        targetMsgId: scrollToTargetId.current,
        targetId,
        totalMessages: allMessages.length,
        messageIds: allMessages.map(m => m.msg_id),
        hasTargetInMessages: allMessages.some(m => m.msg_id === scrollToTargetId.current)
      })
      
      // Enfocar el mensaje de forma determinista, compensando layout shifts.
      isFocusingTarget.current = true
      isAutoScrolling.current = true
      setIsAtBottom(false)

      const container = messagesContainerRef.current
      const startedAt = performance.now()
      const maxMs = 4500
      const tolerancePx = 2
      const stableFramesRequired = 12 // ~200ms a 60fps
      const guardMs = 2000 // seguir corrigiendo shifts tardíos un rato
      let rafId = 0
      let stableFrames = 0
      let phase = 'focus' // 'focus' | 'guard'
      let guardStartedAt = 0

      // Evitar que scroll-behavior: smooth distorsione el centrado.
      const prevScrollBehavior = container?.style?.scrollBehavior
      if (container) container.style.scrollBehavior = 'auto'

      const clampScrollTop = (el, top) => {
        const maxTop = Math.max(0, el.scrollHeight - el.clientHeight)
        return Math.min(maxTop, Math.max(0, top))
      }

      const stopFocus = () => {
        if (rafId) cancelAnimationFrame(rafId)
        rafId = 0
        isAutoScrolling.current = false
        isFocusingTarget.current = false
        if (messagesContainerRef.current) {
          const current = messagesContainerRef.current
          current.style.scrollBehavior = prevScrollBehavior || ''
        }
      }

      const onUserScrollIntent = () => {
        // Si el usuario empieza a hacer wheel/touch durante el focus, parar para no pelear.
        stopFocus()
      }

      if (container) {
        container.addEventListener('wheel', onUserScrollIntent, { passive: true })
        container.addEventListener('touchstart', onUserScrollIntent, { passive: true })
      }

      const focusTick = () => {
        const containerEl = messagesContainerRef.current
        const targetElement = containerEl?.querySelector(`#${targetId}`) || document.getElementById(targetId)

        if (!containerEl || !targetElement) {
          // Si el DOM aún no está listo, reintentar un poco.
          if (performance.now() - startedAt < maxMs) {
            rafId = requestAnimationFrame(focusTick)
          } else {
            console.error('❌ No se encontró el elemento con ID:', targetId)
            console.log(
              '📋 IDs disponibles en el DOM:',
              Array.from(containerEl?.querySelectorAll('[id^="msg-"]') || []).map(el => el.id)
            )
            stopFocus()
          }
          return
        }

        const containerRect = containerEl.getBoundingClientRect()
        const targetRect = targetElement.getBoundingClientRect()
        const containerCenterY = containerRect.top + containerEl.clientHeight / 2
        const targetCenterY = targetRect.top + targetRect.height / 2
        const error = targetCenterY - containerCenterY

        // Ajuste instantáneo (sin smooth) para que sea exacto.
        if (Math.abs(error) > tolerancePx) {
          stableFrames = 0
          const nextTop = clampScrollTop(containerEl, containerEl.scrollTop + error)
          containerEl.scrollTop = nextTop
        } else {
          stableFrames += 1
        }

        const elapsed = performance.now() - startedAt
        if (phase === 'focus') {
          // No terminar al primer "acierto": exigir estabilidad varios frames.
          if (stableFrames >= stableFramesRequired) {
            phase = 'guard'
            guardStartedAt = performance.now()

            targetElement.classList.add('highlight-message')
            setTimeout(() => targetElement.classList.remove('highlight-message'), 3000)

            hasScrolledToTarget.current = true
            scrollToTargetId.current = null
          }

          if (elapsed >= maxMs) {
            // Aunque no se haya estabilizado, entrar en guard un rato (mejor que cortar seco).
            phase = 'guard'
            guardStartedAt = performance.now()

            targetElement.classList.add('highlight-message')
            setTimeout(() => targetElement.classList.remove('highlight-message'), 3000)

            hasScrolledToTarget.current = true
            scrollToTargetId.current = null
          }
        }

        if (phase === 'guard') {
          const guardElapsed = performance.now() - guardStartedAt
          // En guard, solo corregir si hay shift notable; si ya está estable, simplemente dejar pasar.
          if (guardElapsed >= guardMs) {
            stopFocus()
            return
          }
        }

        rafId = requestAnimationFrame(focusTick)
      }

      // Pequeño delay inicial para que React pinte todo antes del primer tick.
      const t = setTimeout(() => {
        console.log('🔍 Iniciando focus loop para:', targetId)
        rafId = requestAnimationFrame(focusTick)
      }, 50)

      return () => {
        clearTimeout(t)
        if (container) {
          container.removeEventListener('wheel', onUserScrollIntent)
          container.removeEventListener('touchstart', onUserScrollIntent)
        }
        stopFocus()
      }
    }
  }, [allMessages, loading])

  // Auto-scroll post-render SOLO si el usuario estaba pegado abajo antes del update.
  useEffect(() => {
    if (!pendingAutoScrollToBottom.current) return

    // Si el usuario se fue arriba entre medias, no pelear.
    if (!stickToBottomRef.current) {
      pendingAutoScrollToBottom.current = false
      return
    }

    if (
      !isInitialLoad.current &&
      allMessages.length > 0 &&
      messagesEndRef.current &&
      !beforeId &&
      !isLoadingOlder.current &&
      !isFocusingTarget.current &&
      !scrollToTargetId.current
    ) {
      isAutoScrolling.current = true
      stickToBottomRef.current = true
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
      setIsAtBottom(true)
      setTimeout(() => { isAutoScrolling.current = false }, 500)
    }

    pendingAutoScrollToBottom.current = false
  }, [allMessages.length, beforeId])

  // Scroll inmediato cuando el usuario vuelve al fondo manualmente
  useEffect(() => {
    if (!isInitialLoad.current && isAtBottom && allMessages.length > 0 && messagesEndRef.current && !isFocusingTarget.current && !scrollToTargetId.current) {
      isAutoScrolling.current = true
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
      setTimeout(() => { isAutoScrolling.current = false }, 500)
    }
  }, [isAtBottom])

  // Restore scroll position after prepending older messages (mantener vista estable)
  useEffect(() => {
    if (!isLoadingOlder.current) return
    const container = messagesContainerRef.current
    if (!container) return

    const prevHeight = preLoadScrollHeightRef.current
    const prevTop = preLoadScrollTopRef.current
    if (prevHeight == null || prevTop == null) return

    requestAnimationFrame(() => {
      const el = messagesContainerRef.current
      if (!el) return

      const newHeight = el.scrollHeight
      const delta = newHeight - prevHeight
      el.scrollTop = prevTop + delta

      // Limpiar flags/refs
      preLoadScrollHeightRef.current = null
      preLoadScrollTopRef.current = null
      isLoadingOlder.current = false
      anchorMessageId.current = null

      // Limpiar ambos valores - el auto-refresh reactivará after_id
      setBeforeId(undefined)
      setAfterId(undefined)
    })
  }, [allMessages])

  // Check if user is at bottom
  const handleScroll = (e) => {
    // Ignorar eventos de scroll durante auto-scroll automático o carga de histórico
    if (isAutoScrolling.current || isLoadingOlder.current) {
      return
    }

    const container = e.target
    const atBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight <
      BOTTOM_STICKY_THRESHOLD_PX
    stickToBottomRef.current = atBottom
    setIsAtBottom(atBottom)

    // Detectar si estamos en el tope
    const atTop = container.scrollTop < 50
    setIsAtTop(atTop)

    // Precarga de histórico SOLO cuando quedan <=200 mensajes visibles por arriba.
    // Usamos 2 estrategias para detectar el mensaje superior visible:
    // - elementFromPoint (rápido)
    // - fallback por scan de anclas (robusto con overlays/espacios)
    if (!pagingEnabledRef.current) {
      return
    }

    if (!loading && !isLoadingOlder.current && visibleMessages.length > 0) {
      let topMsgId = null

      try {
        const rect = container.getBoundingClientRect()
        const elAtTop = document.elementFromPoint(rect.left + 8, rect.top + 8)
        const msgEl = elAtTop && container.contains(elAtTop)
          ? elAtTop.closest('[data-msg-id]')
          : null
        topMsgId = msgEl?.getAttribute('data-msg-id') || null
      } catch {
        topMsgId = null
      }

      if (!topMsgId) {
        const anchors = container.querySelectorAll('[data-msg-id]')
        const scrollTop = container.scrollTop
        for (let i = 0; i < anchors.length; i += 1) {
          const el = anchors[i]
          // offsetTop es relativo al offsetParent; en este layout funciona bien.
          // Elegimos el primer elemento que está en/por debajo del top visible.
          if (el.offsetTop + el.offsetHeight >= scrollTop + 1) {
            topMsgId = el.getAttribute('data-msg-id')
            break
          }
        }
      }

      if (topMsgId) {
        const topIdNum = Number(topMsgId)
        const indexInVisible = visibleMessages.findIndex((m) => m.msg_id === topIdNum)
        if (indexInVisible !== -1 && indexInVisible <= TOP_PREFETCH_VISIBLE_THRESHOLD) {
          handleLoadOlder()
        }
      }
    }
  }

  const handleLoadOlder = () => {
    // Pedir mensajes anteriores al más antiguo que tenemos
    if (oldestMsgId && !loading && !isLoadingOlder.current) {
      if (!pagingEnabledRef.current) {
        return
      }

      // Si aún estaba corriendo el scroll forzado de "abrir chat", cancelarlo.
      if (typeof openScrollCancelRef.current === 'function') {
        openScrollCancelRef.current()
      }
      forceScrollToBottomOnOpenRef.current = false
      cancelOpenScrollRef.current = true

      // Capturar estado de scroll antes de prepend para evitar saltos
      const container = messagesContainerRef.current
      if (container) {
        preLoadScrollHeightRef.current = container.scrollHeight
        preLoadScrollTopRef.current = container.scrollTop
      } else {
        preLoadScrollHeightRef.current = null
        preLoadScrollTopRef.current = null
      }

      isLoadingOlder.current = true
      // Para histórico SOLO before_id, desactivar after_id y around_id
      setBeforeId(oldestMsgId)
      setAfterId(undefined)
      setAroundId(undefined)
    }
  }

  const handleScrollToBottom = () => {
    isAutoScrolling.current = true
    stickToBottomRef.current = true
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    setIsAtBottom(true)
    setTimeout(() => { isAutoScrolling.current = false }, 500)
  }

  // Auto-refresh every 5 seconds to get new messages
  useEffect(() => {
    const interval = setInterval(() => {
      // Siempre buscar mensajes nuevos con after_id
      // Resetear before_id y around_id para evitar mezclarlo
      if (pagingEnabledRef.current && newestMsgId && !isLoadingOlder.current && !aroundId && !beforeId) {
        setAfterId(newestMsgId)
        // Forzar refetch aunque afterId sea el mismo valor
        setRefreshNonce((n) => n + 1)
      }
    }, 5000)

    return () => clearInterval(interval)
  }, [newestMsgId, aroundId, beforeId])

  return (
    <div className="chat-messages-view">
      {/* Scrollable Messages Container */}
      <div 
        className="messages-container" 
        ref={messagesContainerRef}
        onScroll={handleScroll}
      >
        {loading && allMessages.length === 0 ? (
          <Loader text="Cargando mensajes..." />
        ) : (
          <>
            {isSearchView && !pagingEnabled && (
              <div className="paging-gate">
                <div className="paging-gate-text">
                  Carga automática desactivada (modo búsqueda).
                </div>
                <Button
                  size="small"
                  onClick={enablePaging}
                  disabled={loading}
                >
                  Permitir carga de mensajes
                </Button>
              </div>
            )}

            {hasMore && allMessages.length > 0 && (
              <div className="load-older-indicator">
                {loading ? (
                  <span className="loading-text">⬆️ Cargando mensajes antiguos...</span>
                ) : isAtTop ? (
                  <button 
                    className="btn-load-more" 
                    onClick={handleLoadOlder}
                    disabled={loading}
                  >
                    📜 Cargar más histórico
                  </button>
                ) : (
                  <span className="scroll-hint">⬆️ Scroll arriba para cargar más</span>
                )}
              </div>
            )}

            <div className="messages-list">
              {visibleMessages.length > 0 ? (
                visibleMessages.map((message) => (
                  <div
                    key={message.msg_id}
                    id={`msg-${message.msg_id}`}
                    data-msg-id={message.msg_id}
                    className="message-anchor"
                  >
                    <Card className="message-card">
                      <div className="message-header">
                        <div className="message-header-left">
                          <span className="message-id">#{message.msg_id}</span>
                          <span className="message-sender">
                            {(() => {
                              const senderBits = []
                              const fullName = [message.sender_first_name, message.sender_last_name]
                                .filter(Boolean)
                                .join(' ')
                                .trim()
                              if (fullName) senderBits.push(fullName)
                              if (message.sender_username) senderBits.push(`@${message.sender_username}`)

                              const senderLabel = senderBits.length ? ` (${senderBits.join(' ')})` : ''
                              return `Sender: ${message.sender_id ?? 'N/A'}${senderLabel}`
                            })()}
                          </span>
                        </div>

                        <span className="message-date">{formatDateTimeDMYHMS(message.created_at)}</span>
                      </div>

                      {message.text && (
                        <div className="message-text">{message.text}</div>
                      )}

                      {message.media_file_path && (
                        <div className="message-media">
                          <div className="media-info">
                            <Badge variant="secondary">{message.media_type || 'Media'}</Badge>
                          </div>
                          <button
                            type="button"
                            className="media-open"
                            onClick={() => openMediaViewer(message)}
                            title="Ver media en grande"
                          >
                            {message.media_type?.includes('image') || message.media_type?.includes('photo') ? (
                              <img
                                src={apiService.getMediaUrl(message.media_file_path)}
                                alt="Media"
                                className="media-preview"
                                loading="lazy"
                              />
                            ) : (
                              <div className="media-file">
                                <span>📄 {message.media_file_path.split('/').pop()}</span>
                              </div>
                            )}
                          </button>
                        </div>
                      )}
                    </Card>
                  </div>
                ))
              ) : (
                <div className="empty-state">
                  <p>No hay mensajes para mostrar</p>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {!isAtBottom && (
              <button className="scroll-to-bottom" onClick={handleScrollToBottom}>
                ⬇️ Ir abajo
              </button>
            )}
          </>
        )}
      </div>

      {mediaViewer && (
        <div className="media-viewer-overlay">
          <div className="media-viewer-frame">
            <button
              type="button"
              className="media-viewer-close"
              onClick={() => setMediaViewer(null)}
              aria-label="Cerrar visualizador"
              title="Cerrar"
            >
              ✕
            </button>
            <div className="media-viewer-content">
              {(mediaViewer.mediaType.includes('image') || mediaViewer.mediaType.includes('photo')) && (
                <img className="media-viewer-media" src={mediaViewer.url} alt={mediaViewer.fileName || 'Media'} />
              )}

              {mediaViewer.mediaType.includes('video') && (
                <video className="media-viewer-media" src={mediaViewer.url} controls />
              )}

              {(mediaViewer.mediaType.includes('audio') || mediaViewer.mediaType.includes('voice')) && (
                <audio className="media-viewer-audio" src={mediaViewer.url} controls />
              )}

              {!mediaViewer.mediaType.includes('image') &&
                !mediaViewer.mediaType.includes('photo') &&
                !mediaViewer.mediaType.includes('video') &&
                !mediaViewer.mediaType.includes('audio') &&
                !mediaViewer.mediaType.includes('voice') && (
                  <div className="media-viewer-file">
                    <div className="media-viewer-file-name">{mediaViewer.fileName}</div>
                    <a className="media-viewer-file-link" href={mediaViewer.url} target="_blank" rel="noreferrer">
                      Abrir archivo
                    </a>
                  </div>
                )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
