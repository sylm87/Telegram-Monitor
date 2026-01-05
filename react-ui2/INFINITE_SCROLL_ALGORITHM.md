# Algoritmo de Infinite Scroll y Auto-scroll para Chat

## Problema Original
Al cargar mensajes históricos en un chat, el scroll se movía y el usuario perdía su posición de lectura. El auto-scroll también se activaba incorrectamente durante la carga de histórico.

## Solución Implementada

### 1. Variables de Estado Críticas

```javascript
const [oldestMsgId, setOldestMsgId] = useState(null)  // ID del mensaje más antiguo cargado
const [newestMsgId, setNewestMsgId] = useState(null)  // ID del mensaje más reciente cargado
const isLoadingOlder = useRef(false)                  // Flag: cargando histórico
const anchorMessageId = useRef(null)                  // ID del mensaje ancla visual
const isAutoScrolling = useRef(false)                 // Flag: auto-scroll en progreso
```

### 2. Algoritmo de Carga de Mensajes Históricos

#### Paso 1: Guardar Ancla Visual
Antes de agregar mensajes antiguos, guardamos el ID del primer mensaje visible:

```javascript
if (isLoadingOlder.current) {
  const container = messagesContainerRef.current
  if (container && allMessages.length > 0) {
    // El primer mensaje del array es el más antiguo visible
    anchorMessageId.current = allMessages[0].msg_id
  }
  
  // Agregar mensajes antiguos al principio
  setAllMessages(prev => [...sortedMessages, ...prev])
  setOldestMsgId(sortedMessages[0].msg_id)
}
```

#### Paso 2: Restaurar Posición Visual
Después de que React actualice el DOM con los nuevos mensajes, restauramos la posición:

```javascript
useEffect(() => {
  if (isLoadingOlder.current && anchorMessageId.current && messagesContainerRef.current) {
    // Buscar el elemento DOM del mensaje ancla
    const anchorElement = document.querySelector(`[data-msg-id="${anchorMessageId.current}"]`)
    
    if (anchorElement) {
      // Hacer scroll para que el ancla vuelva a la misma posición visual
      anchorElement.scrollIntoView({ block: 'start', behavior: 'instant' })
    }
    
    // Limpiar flags
    isLoadingOlder.current = false
    anchorMessageId.current = null
    setFilters(prev => ({ ...prev, before_id: null }))
  }
}, [allMessages])
```

**Clave del algoritmo**: Usar `data-msg-id` en cada elemento del DOM para poder encontrarlo después de la actualización:

```jsx
<Card key={message.msg_id} className="message-card" data-msg-id={message.msg_id}>
```

### 3. Detección de Scroll para Carga Automática

Cargar histórico cuando el usuario está en el 10% superior del scroll:

```javascript
const handleScroll = (e) => {
  if (isAutoScrolling.current || isLoadingOlder.current) {
    return  // Ignorar eventos durante operaciones automáticas
  }

  const container = e.target
  const scrollPercentage = (container.scrollTop / container.scrollHeight) * 100
  
  if (scrollPercentage < 10 && hasMore && !loading && !isLoadingOlder.current) {
    handleLoadOlder()
  }
}
```

### 4. Sistema de Auto-scroll Inteligente

#### Reglas de Auto-scroll:
1. **Carga inicial**: Scroll automático al final UNA VEZ
2. **Mensajes nuevos**: Auto-scroll SOLO si `isAtBottom = true`
3. **Carga de histórico**: NO auto-scroll (mantener posición)

```javascript
// Auto-scroll SOLO cuando llegan mensajes nuevos Y estás en el fondo
useEffect(() => {
  if (!isInitialLoad.current && 
      !isLoadingOlder.current && 
      isAtBottom && 
      allMessages.length > 0 && 
      messagesEndRef.current) {
    
    isAutoScrolling.current = true
    messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
    setTimeout(() => { isAutoScrolling.current = false }, 500)
  }
}, [allMessages.length, isAtBottom])
```

### 5. Carga Incremental Bidireccional

#### Mensajes Antiguos (hacia arriba):
```javascript
const handleLoadOlder = () => {
  if (oldestMsgId && !loading && !isLoadingOlder.current) {
    isLoadingOlder.current = true
    setFilters(prev => ({ ...prev, before_id: oldestMsgId }))
  }
}
```

#### Mensajes Nuevos (hacia abajo):
```javascript
// Refresh de mensajes nuevos - solo agregar los más recientes
const newMessages = sortedMessages.filter(msg => msg.msg_id > newestMsgId)
if (newMessages.length > 0) {
  setAllMessages(prev => [...prev, ...newMessages])
  setNewestMsgId(newMessages[newMessages.length - 1].msg_id)
}
```

### 6. Prevención de Conflictos

#### Ignorar scroll durante operaciones automáticas:
```javascript
const handleScroll = (e) => {
  if (isAutoScrolling.current || isLoadingOlder.current) {
    return  // Evita que el scroll manual interfiera
  }
  // ... resto del código
}
```

#### Auto-refresh inteligente:
```javascript
useEffect(() => {
  const interval = setInterval(() => {
    if (!isLoadingOlder.current) {  // No refresh durante carga de histórico
      setFilters(prev => ({ ...prev, before_id: null }))
    }
  }, 5000)
  return () => clearInterval(interval)
}, [])
```

## Ventajas de esta Solución

✅ **Mantiene posición visual exacta** durante carga de histórico  
✅ **Auto-scroll inteligente** solo cuando es apropiado  
✅ **Carga fluida** al 10% superior (no espera a llegar arriba)  
✅ **Sin conflictos** entre scroll manual y automático  
✅ **Carga incremental** eficiente (solo trae lo que falta)  
✅ **Experiencia tipo Telegram** fluida y predecible  

## Comportamiento del Usuario

1. **Al abrir chat**: Scroll automático al final
2. **Mensajes nuevos llegan**:
   - Si estás abajo (20px): Auto-scroll
   - Si estás arriba: Solo agrega, sin mover
3. **Scroll hacia arriba**: Carga automática de histórico al llegar al 10%
4. **Durante carga de histórico**: Tu posición visual NO cambia
5. **Botón "Ir abajo"**: Scroll suave + reactiva auto-scroll

## Archivo Implementado

`react-ui2/src/views/ChatMessages.jsx`

Backup funcional guardado en:  
`react-ui2/src/views/ChatMessages.jsx.backup`
