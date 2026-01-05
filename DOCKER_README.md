# 🐳 Telegram-monitor — Docker / Compose

Este documento describe el despliegue actual del sistema usando Docker Compose, con **build contexts por carpeta** y **separación de variables sensibles por cliente**.

## ⚙️ Requisitos

- Docker Desktop (Windows) con `docker compose` (v2)
- Acceso a Telegram API (API ID / API HASH en https://my.telegram.org/apps)

## 🧱 Servicios (docker-compose.yml)

- **postgres** (`telegram-db`): PostgreSQL con esquema inicial embebido en la imagen.
- **telegram-client-1** (`telegram-client-1`): cliente Telethon que captura mensajes + catch-up + descargas.
- **telegram-api-gest** (`telegram-api-gest`): API FastAPI que consulta Postgres y sirve media.
- **telegram-front-gest** (`telegram-front-gest`): UI React/Vite (servidor dev expuesto por Docker).
- **telegram-init** (perfil `init`): utilitario interactivo para generar `TG_SESSION_STRING`.

## 📁 Estructura actual del repo (relevante para Docker)

```text
postgres/
  Dockerfile
  init_db.sql

telegram_client/
  Dockerfile
  requirements.txt
  main.py
  db.py

fastapi-api/
  Dockerfile
  requirements.txt
  main.py

react-ui2/
  Dockerfile
  package.json
  src/...

utils/
  (scripts de diagnóstico/pruebas y reportes)
```

## 🔐 Variables de entorno

### 1) `.env` (compartido)

Se carga en `postgres`, `telegram-api-gest` y como base para los clientes.

Variables típicas:

```env
# Telegram API
TG_API_ID=<tu_api_id>
TG_API_HASH=<tu_api_hash>

# Postgres (preferidas)
POSTGRES_DB=telegram_monitor
POSTGRES_USER=telegram
POSTGRES_PASSWORD=<tu_password>
POSTGRES_PORT=5432

# Opcional
API_BASE=http://localhost:8000
```

Notas:
- `DB_*` sigue siendo compatible (por código), pero el despliegue actual usa `POSTGRES_*`.
- No metas aquí `TG_PHONE`/`TG_SESSION_STRING` si quieres aislar secretos por cliente.

### 2) `.env.client1` (solo cliente 1)

Se carga **solo** en `telegram-client-1`.

```env
TG_PHONE=+34XXXXXXXXX
TG_SESSION_STRING=<string_session>
```

## 🧾 Inicialización desde cero (Windows)

### 0) Preparar carpetas host (bind mounts)

El compose actual monta estas rutas (ajústalas a tu máquina):

- `D:\MONITOR_TEL_DATA\postgresql_telegram_data`  → datos Postgres
- `D:\MONITOR_TEL_DATA\media_downloads` → ficheros descargados
- `D:\MONITOR_TEL_DATA\logs\+<phone>\err-logs` → errores
- `D:\MONITOR_TEL_DATA\logs\+<phone>\out-logs` → salida

Para que Postgres ejecute `postgres/init_db.sql`, la carpeta de datos debe estar **vacía** en el primer arranque.

### 1) Generar `TG_SESSION_STRING`

Ejecuta el perfil `init` (interactivo). Puedes pasar el teléfono por `-e` y luego copiar el string a `.env.client1`.

```powershell
docker compose --profile init run --rm -e TG_PHONE="+34XXXXXXXXX" telegram-init
```

Salida esperada: imprime una línea `TG_SESSION_STRING=...`.

### 2) Arrancar todo

```powershell
docker compose up -d --build
docker compose ps
```

## ✅ Verificaciones rápidas

### Estado

```powershell
docker compose ps
```

### Logs

```powershell
docker compose logs -f telegram-client-1
docker compose logs -f telegram-api-gest
docker compose logs -f postgres
```

### UI y API

- UI: `http://localhost:3000`
- API: `http://localhost:8000/health`

## 🧰 Utilidades

Scripts moved a `utils/`:

```powershell
.\utils\view-logs.ps1
.\utils\view-errors.ps1
```

## ♻️ Operaciones comunes

```powershell
# bajar todo
docker compose down

# bajar y reconstruir
docker compose down
docker compose up -d --build

# ver contenedores
docker compose ps
```

## 🧠 Nota importante sobre el esquema de BD

El sistema está diseñado para que la **creación del esquema dependa solo de Postgres** (imagen `postgres/`).

- Ni el cliente ni la API crean tablas/columnas en runtime.
- Si falta esquema, fallarán con un error explícito para que el problema sea visible.

---

## 🐛 Troubleshooting

### Postgres no llega a "healthy" / errores de conexión

```powershell
docker compose ps
docker compose logs -f postgres
docker inspect telegram-db --format='{{.State.Health.Status}}'
```

Notas:

- El init SQL solo corre si `D:\MONITOR_TEL_DATA\postgresql_telegram_data` está vacío en el primer arranque.
- El puerto publicado es `${POSTGRES_PORT:-5432}` en el host.

### Sesión inválida o el cliente necesita login interactivo

Genera un nuevo `TG_SESSION_STRING` con el perfil init:

```powershell
docker compose --profile init run --rm -e TG_PHONE="+34XXXXXXXXX" telegram-init
```

Pega el valor en `.env.client1` y reinicia el cliente:

```powershell
docker compose restart telegram-client-1
```

### Comprobar conexión a BD desde el contenedor del cliente

```powershell
docker exec telegram-client-1 python -c "from telegram_client.db import get_db_connection; c=get_db_connection(); print('OK'); c.close()"
```

### Reinicio desde cero (CUIDADO: borra datos)

Este despliegue usa **bind mounts** (carpetas host), no volúmenes. Para un reset completo:

```powershell
docker compose down
```

- Borra (o renombra) `D:\MONITOR_TEL_DATA\postgresql_telegram_data`.
- Opcional: borra `D:\MONITOR_TEL_DATA\media_downloads` y logs si quieres limpiar totalmente.
- Arranca de nuevo:

```powershell
docker compose up -d --build
```

---

## 📝 Notas

- El esquema se crea desde `postgres/init_db.sql` dentro del contenedor `postgres/`.
- `TG_PHONE` y `TG_SESSION_STRING` deben ir en `.env.clientN` (no en `.env`) si quieres aislar secretos por cliente.
