FROM postgres:15-alpine

# Inicializa el esquema al crear el volumen por primera vez.
# Este script se ejecuta SOLO si /var/lib/postgresql/data está vacío.
COPY init_db.sql /docker-entrypoint-initdb.d/001_init_db.sql
