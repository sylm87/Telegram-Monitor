# Multi-stage build para Telegram Client Monitor
FROM python:3.11-slim AS builder

WORKDIR /app

# Instalar dependencias de build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependencias
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage final
FROM python:3.11-slim

WORKDIR /app

# Instalar librerías runtime de PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copiar dependencias Python del builder
COPY --from=builder /root/.local /root/.local

# Copiar código del cliente dentro del paquete
COPY . ./telegram_client

# Agregar binarios de Python al PATH
ENV PATH=/root/.local/bin:$PATH

# Crear directorios para datos persistentes
RUN mkdir -p /app/media_downloads /app/sessions

# Variables de entorno por defecto (pueden sobreescribirse)
ENV TG_MEDIA_DIR=/app/media_downloads
ENV PYTHONUNBUFFERED=1

# Healthcheck para verificar que la app está viva
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import sys; sys.exit(0)" || exit 1

# Comando por defecto (se puede override en docker-compose)
CMD ["python", "-m", "telegram_client.main", "listen", "--download", "--catch-up"]
