# Telegram Monitor UI

Interfaz moderna para monitoreo y gestión de chats de Telegram con tema hacker verde/negro.

## 🚀 Características

- **Dashboard**: Estadísticas en tiempo real de la cola de mensajes
- **Gestión de Chats**: Listado, filtrado y configuración de chats
- **Búsqueda Avanzada**: Búsqueda de mensajes con filtros múltiples
- **Tema Hacker**: Diseño verde/negro estilo terminal
- **Responsive**: Adaptado a todos los dispositivos
- **Auto-refresh**: Actualización automática de estadísticas

## 🛠️ Tecnologías

- React 18
- Vite 5
- CSS Modules
- Fetch API

## 📦 Instalación

```bash
# Instalar dependencias
npm install

# Iniciar servidor de desarrollo
npm run dev

# Compilar para producción
npm run build

# Previsualizar build de producción
npm run preview
```

## 🐳 Docker

```bash
# Construir imagen
docker build -t telegram-monitor-ui .

# Ejecutar contenedor
docker run -p 3000:3000 telegram-monitor-ui
```

## ⚙️ Configuración

Crear archivo `.env` en la raíz del proyecto:

```env
VITE_API_BASE=http://localhost:8000
```

## 📁 Estructura del Proyecto

```
react-ui2/
├── src/
│   ├── components/      # Componentes reutilizables
│   │   ├── Button.jsx
│   │   ├── Input.jsx
│   │   ├── Card.jsx
│   │   ├── Loader.jsx
│   │   └── Badge.jsx
│   ├── views/          # Vistas principales
│   │   ├── Dashboard.jsx
│   │   ├── Chats.jsx
│   │   ├── ChatMessages.jsx
│   │   └── Search.jsx
│   ├── services/       # Servicios API
│   │   └── api.js
│   ├── hooks/          # Custom hooks
│   │   └── index.js
│   ├── utils/          # Utilidades
│   │   └── helpers.js
│   ├── App.jsx         # Componente principal
│   ├── main.jsx        # Entry point
│   └── index.css       # Estilos globales
├── public/
├── index.html
├── package.json
├── vite.config.js
└── Dockerfile
```

## 🎨 Tema

El proyecto utiliza un tema hacker con los siguientes colores:

- **Primary**: `#00ff00` (Verde neón)
- **Secondary**: `#00ffff` (Cyan)
- **Background**: `#000000` (Negro)
- **Text**: `#00ff00` (Verde)

## 🔧 API Integration

La aplicación se conecta a la API FastAPI backend. Asegúrate de que el backend esté corriendo en `http://localhost:8000` o configura la variable `VITE_API_BASE`.

## 📝 Uso

1. **Dashboard**: Visualiza estadísticas de la cola de mensajes
2. **Chats**: Explora y gestiona tus chats
3. **Búsqueda**: Busca mensajes específicos en todos los chats

## 🤝 Contribuir

Las contribuciones son bienvenidas. Por favor, abre un issue primero para discutir los cambios que te gustaría hacer.

## 📄 Licencia

Este proyecto es de código abierto y está disponible bajo la licencia MIT.
