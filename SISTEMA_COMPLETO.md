# SISTEMA COMPLETO — Telegram-monitor

Este documento describe el estado **actual** del sistema: arquitectura, modelo de datos en PostgreSQL, comportamiento interno del cliente Telegram, API y frontend.

## 🎯 Objetivo

- Ingestar mensajes de Telegram (tiempo real + histórico) en PostgreSQL.
- Gestionar una **cola de descargas** de media con prioridad “small first”.
- Exponer una API para monitorizar chats/mensajes/descargas y servir ficheros.
- Proveer una UI web con auto-refresco.

## 🧩 Arquitectura (alto nivel)

```text
Telegram (MTProto)
   │
   ▼
telegram-client-N (Telethon)
   ├─ inserta/actualiza chats, senders, messages
   ├─ guarda historial (message_log)
   ├─ encola descargas (download_queue)
   └─ descarga media al filesystem
         │
         ├─ PostgreSQL (tablas)
         └─ /app/media_downloads/<account_phone>/<chat_id>/<media_type>/...

fastapi-api
   ├─ consulta PostgreSQL
   └─ sirve media (FileResponse) desde /app/media_downloads

react-ui2
   └─ consume fastapi-api (polling cada ~5s para stats/pantallas principales)
```

## 🐳 Servicios Docker (compose)

- **postgres**: imagen construida desde `postgres/`.
  - Contiene el esquema en `postgres/init_db.sql`.
  - Importante: el init SQL solo se ejecuta cuando el directorio de datos está vacío.
- **telegram-client-1**: imagen desde `telegram_client/`.
  - Se ejecuta como módulo: `python -m telegram_client.main listen --catch-up --download`.
- **telegram-api-gest**: imagen desde `fastapi-api/`.
- **telegram-front-gest**: imagen desde `react-ui2/` (Vite dev server).

## 💾 Base de datos (arquitectura y tablas)

El esquema se crea **solo** desde PostgreSQL en `postgres/init_db.sql`. Ni el cliente ni la API hacen DDL en runtime.

### Principio clave: multi-cuenta por `account_phone`

Todas las tablas “de negocio” incluyen `account_phone` para que múltiples clientes (distintas líneas) compartan la misma BD sin mezclar datos.

### Tablas

#### 1) `chats`

- Identidad: `(chat_id, account_phone)`
- Contenido: `username`, `title`, `chat_type`, `updated_at`

#### 2) `senders`

- Identidad: `(user_id, account_phone)`
- Contenido: `username`, `first_name`, `last_name`, `is_bot`, `updated_at`

#### 3) `messages`

- Identidad: `(chat_id, msg_id, account_phone)`
- Campos relevantes: `sender_id`, `text`, `media_type`, `media_file_path`, `created_at`, `received_at`, flags (forward/pin/etc)
- Relación:
  - FK a `chats(chat_id, account_phone)`
  - Nota: `sender_id` y `forward_sender_id` no tienen FK; la integridad se maneja en aplicación y consultas hacen `LEFT JOIN`.

#### 4) `message_log`

- Propósito: historial/registro de eventos/ediciones por mensaje.
- Relación: FK a `messages(chat_id, msg_id, account_phone)`.
- No hay `UNIQUE` intencionalmente para permitir múltiples entradas (por ejemplo, ediciones).

#### 5) `download_queue`

- Propósito: cola de descargas de media.
- Identidad: `id (SERIAL)`
- Unicidad: `UNIQUE(chat_id, msg_id, account_phone)`
- Campos: `status` (`pending`/`in_progress`/`done`/`failed`), `path`, `error`, `attempts`, `updated_at`, `file_size`, `file_unique_id`.

#### 6) `chat_preferences`

- Propósito: activar/desactivar descarga de media por chat y cuenta.
- PK: `(chat_id, account_phone)`
- Campo: `media_download_enabled` (default `TRUE`).

### Índices

El init SQL crea índices orientados a:

- Consultas por chat/cuenta (`messages(chat_id, account_phone)`)
- Estadísticas de cola (`download_queue(status, account_phone)`)
- Acceso a logs (`message_log(telegram_msg_id, account_phone)`)

## 🤖 Cliente Telegram (internals)

### Sesión y autenticación

El cliente usa Telethon y **siempre** ejecuta con una FileSession (`/app/me.session`) para que funcionen correctamente los event handlers.

- Si existe `TG_SESSION_STRING` y todavía no existe `/app/me.session`, el cliente materializa ese string a un fichero de sesión.
- Si no hay sesión válida, habrá que autenticar de forma interactiva usando el contenedor `telegram-init`.

Variables clave:

- `TG_API_ID`, `TG_API_HASH` (comunes)
- `TG_PHONE` (identidad de cuenta, y se usa como `account_phone` en BD)
- `TG_SESSION_STRING` (secreto por cliente)

### Modos de ejecución (CLI)

El entrypoint es `python -m telegram_client.main` y soporta subcomandos:

- `init` (interactivo, para generar string session)
- `listen` (modo servicio)
- `catch-up` (catch-up puntual de un chat)
- `db-stats`, `db-export`, `db-chat` (utilidades de consulta)

### Flujo de ingesta (tiempo real + catch-up)

En el modo `listen`:

1. Conecta a Telegram.
2. Registra event handlers para mensajes nuevos.
3. Si se activa `--catch-up`, recorre diálogos y hace backfill histórico donde falten mensajes.
4. Persiste cada mensaje:
   - upsert de chat y sender
   - insert/update de `messages`
   - añade entradas a `message_log` cuando aplique
5. Si un mensaje tiene media, puede:
   - encolar en `download_queue`
   - y/o descargar directamente dependiendo del flujo.

### Descargas (cola)

El download worker:

- Trabaja sobre `download_queue` filtrado por `account_phone` (una cuenta no consume descargas de otra).
- Implementa “small first”: prioriza `file_size` más pequeño (`ORDER BY file_size ASC NULLS LAST`).
- Rehidrata tareas atascadas:
  - filas en `in_progress` con antigüedad > N minutos vuelven a `pending`.
- Respeta preferencias:
  - si `chat_preferences.media_download_enabled = FALSE`, el worker no consume esa cola.

### Media en filesystem

Ruta base:

```text
TG_MEDIA_DIR (default /app/media_downloads)
  └─ <TG_PHONE>
      └─ <chat_id>
          └─ <media_type>
              └─ <filename>
```

Adicionalmente se escribe `.metadata.json` por chat en el directorio del chat.

### Logging

- Logs generales: `TG_OUTPUT_LOG` (default `/output/out-logs/tel-cli.output.log`)
- Logs de error: `TG_ERROR_LOG` (default `/output/err-logs/tel-cli.error.log`)

## 🌐 API (FastAPI)

### Conexión a BD

Usa pool de conexiones y configuración vía variables (preferencia `POSTGRES_*`, compatibilidad `DB_*`).

Importante:

- En startup valida que exista `chat_preferences`.
- No crea tablas.

### Endpoints principales

- `GET /health` → ok
- `GET /stats/queue` → estadísticas de cola (incluye “pendientes efectivos” filtrando por `chat_preferences`)
- `GET /chats` → listado con filtros (`account`, `chat_id`, `chat_type`, `search`, `limit`, `offset`)
- `PATCH /chats/{chat_id}/settings?account=...` → activa/desactiva descarga por chat/cuenta
- `GET /chats/{chat_id}/messages?account=...` → mensajes (soporta `before_id`, `after_id`, `around_id`, `limit`, `include_logs`)
- `GET /downloads` → descargas con filtros (`status`, `chat_id`, `limit`, `offset`)
- `GET /chats/{chat_id}/media` → media por chat
- `GET /search/messages` → búsqueda
- `GET /media?path=...` → sirve un fichero dentro de `MEDIA_ROOT` (`/app/media_downloads`)

## 🖥️ Frontend (react-ui2)

### Tecnologías

- React + Vite
- Capa de servicios en `src/services/api.js`

### Configuración

- `VITE_API_BASE` define la base del backend.
- En Docker compose se inyecta como build arg `VITE_API_BASE` (usando `API_BASE` del `.env` como fuente).

### Auto-refresh

Las pantallas principales usan polling:

- Hook `useAutoRefresh(callback, 5000)` para refrescar cada ~5s.
- Dashboard y descargas refrescan stats automáticamente.

## ✅ Operación desde cero (recordatorio)

Para que el esquema se aplique:

- La carpeta bind-mount de datos Postgres debe estar vacía en el primer arranque.
- Luego `docker compose up -d --build`.
