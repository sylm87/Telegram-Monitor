import psycopg2
import psycopg2.extras
import psycopg2.pool
import json
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# PostgreSQL connection parameters
DATABASE_URL = os.environ.get("DATABASE_URL")

# Preferimos variables estándar de Postgres en .env para todos los contenedores.
# Mantenemos compatibilidad con DB_* por si se ejecuta fuera de Docker o en setups antiguos.
_has_postgres_env = any(
    os.environ.get(k)
    for k in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
)

DB_HOST = os.environ.get("DB_HOST") or os.environ.get("POSTGRES_HOST") or (
    "postgres" if _has_postgres_env else "localhost"
)
DB_PORT = os.environ.get("DB_PORT") or os.environ.get("POSTGRES_PORT") or "5432"
DB_NAME = os.environ.get("DB_NAME") or os.environ.get("POSTGRES_DB") or "telegram_monitor"
DB_USER = os.environ.get("DB_USER") or os.environ.get("POSTGRES_USER") or "telegram"
DB_PASSWORD = os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD") or "telegram"

# Connection pool
_connection_pool = None

# El esquema debe ser creado por el contenedor PostgreSQL (init_db.sql).
# Aquí solo validamos su presencia para evitar que el cliente haga DDL.
_schema_checks = {
    "chat_preferences_table": False,
    "download_queue_account_phone": False,
}


def _table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
        row = cur.fetchone()
    return bool(row and list(row.values())[0])


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            LIMIT 1
            """,
            (table_name, column_name),
        )
        return cur.fetchone() is not None

def _get_pool():
    """Obtiene el pool de conexiones (singleton)."""
    global _connection_pool
    if _connection_pool is None:
        if DATABASE_URL:
            _connection_pool = psycopg2.pool.SimpleConnectionPool(
                20, 10000, dsn=DATABASE_URL  # 64 clientes × 25 concurrentes = 1,600 max, pool de 10K para más que suficiente
            )
        else:
            _connection_pool = psycopg2.pool.SimpleConnectionPool(
                20, 10000,  # 64 clientes × 25 concurrentes = 1,600 max, pool de 10K para más que suficiente
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
    return _connection_pool


def get_db_connection():
    """Obtiene conexión a BD desde el pool."""
    pool = _get_pool()
    conn = pool.getconn()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def close_db_connection(conn):
    """Devuelve conexión al pool."""
    pool = _get_pool()
    pool.putconn(conn)


def _init_schema(conn):
    """Crea el esquema de tablas si no existe (PostgreSQL)."""
    with conn.cursor() as cur:
        # El schema se inicializa desde init_db.sql en Docker
        # Esta función solo verifica conectividad
        cur.execute("SELECT 1")
    conn.commit()


def insert_or_update_chat(conn, chat_id: int, username: Optional[str], 
                          title: Optional[str], chat_type: str, account_phone: str):
    """Inserta o actualiza un chat."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO chats (chat_id, username, title, chat_type, account_phone, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (chat_id, account_phone) DO UPDATE SET
                username = EXCLUDED.username,
                title = EXCLUDED.title,
                chat_type = EXCLUDED.chat_type,
                updated_at = CURRENT_TIMESTAMP
        """, (chat_id, username, title, chat_type, account_phone))
    conn.commit()


def insert_or_update_sender(conn, user_id: int, username: Optional[str],
                            first_name: Optional[str], last_name: Optional[str], is_bot: bool = False, account_phone: str = None):
    """Inserta o actualiza un remitente."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO senders (user_id, username, first_name, last_name, is_bot, account_phone, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, account_phone) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                is_bot = EXCLUDED.is_bot,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, username, first_name, last_name, is_bot, account_phone))
    conn.commit()


def insert_message(conn, msg_id: int, chat_id: int, sender_id: Optional[int],
                  text: Optional[str], media_type: Optional[str], media_file_path: Optional[str],
                  is_forward: bool, forward_sender_id: Optional[int], reply_to_msg_id: Optional[int],
                  edit_date: Optional[datetime], views: Optional[int], forwards: Optional[int],
                  pin: bool, silent: bool, is_post: bool, ttl_period: Optional[int],
                  topic_id: Optional[int], has_log: bool, created_at: datetime, account_phone: str) -> bool:
    """Inserta o actualiza un mensaje en la BD (PK compuesta chat_id, msg_id)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (
                    msg_id, chat_id, sender_id, text, media_type, media_file_path,
                    is_forward, forward_sender_id, reply_to_msg_id, edit_date,
                    views, forwards, pin, silent, is_post, ttl_period, topic_id,
                    has_log, created_at, account_phone
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(chat_id, msg_id, account_phone) DO UPDATE SET
                    sender_id=EXCLUDED.sender_id,
                    text=EXCLUDED.text,
                    media_type=EXCLUDED.media_type,
                    media_file_path=EXCLUDED.media_file_path,
                    is_forward=EXCLUDED.is_forward,
                    forward_sender_id=EXCLUDED.forward_sender_id,
                    reply_to_msg_id=EXCLUDED.reply_to_msg_id,
                    edit_date=EXCLUDED.edit_date,
                    views=EXCLUDED.views,
                    forwards=EXCLUDED.forwards,
                    pin=EXCLUDED.pin,
                    silent=EXCLUDED.silent,
                    is_post=EXCLUDED.is_post,
                    ttl_period=EXCLUDED.ttl_period,
                    topic_id=EXCLUDED.topic_id,
                    has_log=EXCLUDED.has_log,
                    created_at=EXCLUDED.created_at,
                    received_at=CURRENT_TIMESTAMP
                """,
                (
                    msg_id,
                    chat_id,
                    sender_id,
                    text,
                    media_type,
                    media_file_path,
                    is_forward,
                    forward_sender_id,
                    reply_to_msg_id,
                    edit_date,
                    views,
                    forwards,
                    pin,
                    silent,
                    is_post,
                    ttl_period,
                    topic_id,
                    has_log,
                    created_at,
                    account_phone,
                ),
            )
        conn.commit()
        return True
    except Exception:
        logger.exception("Error insertando mensaje %s en chat %s", msg_id, chat_id)
        raise


def update_message(conn, msg_id: int, *,
                   chat_id: Optional[int] = None,
                   text: Optional[str] = None,
                   media_type: Optional[str] = None,
                   media_file_path: Optional[str] = None,
                   edit_date: Optional[datetime] = None,
                   views: Optional[int] = None,
                   forwards: Optional[int] = None,
                   pin: Optional[bool] = None,
                   silent: Optional[bool] = None,
                   is_post: Optional[bool] = None,
                   ttl_period: Optional[int] = None,
                   topic_id: Optional[int] = None) -> bool:
    """Actualiza campos de un mensaje existente. Solo actualiza los no-None."""
    fields = []
    values = []

    if text is not None:
        fields.append("text = %s")
        values.append(text)
    if media_type is not None:
        fields.append("media_type = %s")
        values.append(media_type)
    if media_file_path is not None:
        fields.append("media_file_path = %s")
        values.append(media_file_path)
    if edit_date is not None:
        fields.append("edit_date = %s")
        values.append(edit_date)
    if views is not None:
        fields.append("views = %s")
        values.append(views)
    if forwards is not None:
        fields.append("forwards = %s")
        values.append(forwards)
    if pin is not None:
        fields.append("pin = %s")
        values.append(pin)
    if silent is not None:
        fields.append("silent = %s")
        values.append(silent)
    if is_post is not None:
        fields.append("is_post = %s")
        values.append(is_post)
    if ttl_period is not None:
        fields.append("ttl_period = %s")
        values.append(ttl_period)
    if topic_id is not None:
        fields.append("topic_id = %s")
        values.append(topic_id)

    if not fields:
        return False

    fields.append("received_at = CURRENT_TIMESTAMP")
    where_clause = "WHERE msg_id = %s" if chat_id is None else "WHERE msg_id = %s AND chat_id = %s"
    query = f"UPDATE messages SET {', '.join(fields)} {where_clause}"
    values.append(msg_id)
    if chat_id is not None:
        values.append(chat_id)
    
    with conn.cursor() as cur:
        cur.execute(query, values)
    conn.commit()
    return cur.rowcount > 0


def insert_reactions(conn, msg_id: int, chat_id: int, reactions_data: list, account_phone: str = None):
    """Inserta reacciones para un mensaje (se borra y reescribe por idempotencia)."""
    if not reactions_data:
        return

    with conn.cursor() as cur:
        cur.execute("DELETE FROM reactions WHERE msg_id = %s AND chat_id = %s AND account_phone = %s", (msg_id, chat_id, account_phone))
        for reaction in reactions_data:
            emoji = reaction.get("emoji")
            count = reaction.get("count", 1)
            cur.execute(
                """
                INSERT INTO reactions (msg_id, chat_id, emoji, count, account_phone)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (msg_id, chat_id, emoji, count, account_phone),
            )
    conn.commit()


def insert_entities(conn, msg_id: int, chat_id: int, entities_data: list, account_phone: str = None):
    """Inserta entidades (menciones, hashtags, URLs, etc.) para un mensaje."""
    if not entities_data:
        return

    with conn.cursor() as cur:
        cur.execute("DELETE FROM entities WHERE msg_id = %s AND chat_id = %s AND account_phone = %s", (msg_id, chat_id, account_phone))
        for entity in entities_data:
            entity_type = entity.get("type")
            offset = entity.get("offset")
            length = entity.get("length")
            text = entity.get("text")
            cur.execute(
                """
                INSERT INTO entities (msg_id, chat_id, entity_type, entity_offset, entity_length, text, account_phone)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (msg_id, chat_id, entity_type, offset, length, text, account_phone),
            )
    conn.commit()


def insert_message_log(conn, telegram_msg_id: int, chat_id: int, sender_id: Optional[int],
                       text: Optional[str], media_type: Optional[str], media_file_path: Optional[str],
                       is_forward: bool, reply_to_msg_id: Optional[int], edited: bool,
                       edit_date: Optional[datetime], created_at: datetime, account_phone: str):
    """Inserta una versión de mensaje (incluye ediciones) sin sobrescribir el original."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO message_log (
                telegram_msg_id, chat_id, sender_id, text, media_type, media_file_path,
                is_forward, reply_to_msg_id, edited, edit_date, created_at, account_phone
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (telegram_msg_id, chat_id, sender_id, text, media_type, media_file_path,
             is_forward, reply_to_msg_id, edited, edit_date, created_at, account_phone)
        )
        # Marcar mensaje principal como con logs
        cur.execute("UPDATE messages SET has_log = TRUE WHERE msg_id = %s AND chat_id = %s AND account_phone = %s", (telegram_msg_id, chat_id, account_phone))
    conn.commit()


def get_messages_by_chat(conn, chat_id: int, limit: int = 100) -> list:
    """Obtiene últimos N mensajes de un chat."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM messages
            WHERE chat_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (chat_id, limit))
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def get_messages_by_sender(conn, sender_id: int, limit: int = 100) -> list:
    """Obtiene últimos N mensajes de un remitente."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM messages
            WHERE sender_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (sender_id, limit))
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def export_messages_json(conn, output_file: str = "messages_export.json"):
    """Exporta todos los mensajes a JSON."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM messages ORDER BY created_at
        """)
        rows = cur.fetchall()
    
    data = []
    for row in rows:
        msg_dict = dict(row)
        # Obtener reacciones
        with conn.cursor() as cur:
            cur.execute(
                "SELECT emoji, count FROM reactions WHERE msg_id = %s AND chat_id = %s",
                (row["msg_id"], row["chat_id"])
            )
            reactions = cur.fetchall()
        msg_dict["reactions"] = [dict(r) for r in reactions]
        
        # Obtener entidades
        with conn.cursor() as cur:
            cur.execute(
                "SELECT entity_type, entity_offset as offset, entity_length as length, text FROM entities WHERE msg_id = %s AND chat_id = %s",
                (row["msg_id"], row["chat_id"])
            )
            entities = cur.fetchall()
        msg_dict["entities"] = [dict(e) for e in entities]
        
        data.append(msg_dict)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    return len(data)


def get_max_message_id_in_chat(conn, chat_id: int, account_phone: str) -> int:
    """Obtiene el ID de mensaje más alto guardado en un chat para una cuenta específica."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(msg_id) FROM messages WHERE chat_id = %s AND account_phone = %s",
                (chat_id, account_phone)
            )
            result = cur.fetchone()
        max_id = result["max"] if result and result["max"] else 0
        logger.debug(f"get_max_message_id_in_chat({chat_id}, {account_phone}) = {max_id}")
        return max_id
    except Exception as e:
        logger.error(f"Error obteniendo max msg_id para chat {chat_id}: {e}")
        return 0


def get_stats(conn) -> dict:
    """Obtiene estadísticas generales."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM messages")
        total_messages = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM chats")
        total_chats = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM senders")
        total_senders = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM reactions")
        total_reactions = cur.fetchone()["cnt"]
    
    stats = {
        "total_messages": total_messages,
        "total_chats": total_chats,
        "total_senders": total_senders,
        "total_reactions": total_reactions,
    }
    return stats


# ---- Cola de descargas ----

def enqueue_download(conn, msg_id: int, chat_id: int, chat_label: str, media_dir: Optional[str], file_size: Optional[int], file_unique_id: Optional[str], account_phone: str) -> None:
    """Encola un mensaje para descarga de media. Idempotente por msg_id y por file_unique_id."""
    ensure_chat_preferences_table(conn)
    ensure_download_queue_account_phone(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO download_queue (msg_id, chat_id, chat_label, media_dir, file_size, file_unique_id, account_phone)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_id, msg_id, account_phone) DO NOTHING
            """,
            (msg_id, chat_id, chat_label, media_dir, file_size, file_unique_id, account_phone)
        )
    conn.commit()


def fetch_pending_downloads(conn, limit: int = 10, account_phone: Optional[str] = None):
    """Obtiene descargas pendientes priorizando ficheros pequeños.

    Si account_phone se proporciona, limita la cola a esa línea.
    """
    ensure_chat_preferences_table(conn)
    ensure_download_queue_account_phone(conn)
    with conn.cursor() as cur:
        params = []
        where = ["dq.status = 'pending'", "COALESCE(cp.media_download_enabled, TRUE) = TRUE"]
        if account_phone:
            where.append("dq.account_phone = %s")
            params.append(account_phone)

        params.append(limit)
        cur.execute(
            f"""
            SELECT dq.id, dq.msg_id, dq.chat_id, dq.chat_label, dq.media_dir, dq.file_size, dq.file_unique_id, dq.account_phone
            FROM download_queue dq
            LEFT JOIN chat_preferences cp
                ON cp.chat_id = dq.chat_id AND cp.account_phone = dq.account_phone
            WHERE {' AND '.join(where)}
            ORDER BY dq.file_size ASC NULLS LAST, dq.created_at ASC, dq.id ASC
            LIMIT %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_recent_pending_downloads(conn, limit: int = 3, account_phone: Optional[str] = None):
    """Obtiene descargas pendientes priorizando ficheros pequeños (subconjunto reciente).

    Si account_phone se proporciona, limita la cola a esa línea.
    """
    ensure_chat_preferences_table(conn)
    ensure_download_queue_account_phone(conn)
    with conn.cursor() as cur:
        params = []
        where = ["dq.status = 'pending'", "COALESCE(cp.media_download_enabled, TRUE) = TRUE"]
        if account_phone:
            where.append("dq.account_phone = %s")
            params.append(account_phone)

        params.append(limit)
        cur.execute(
            f"""
            SELECT dq.id, dq.msg_id, dq.chat_id, dq.chat_label, dq.media_dir, dq.file_size, dq.file_unique_id, dq.account_phone
            FROM download_queue dq
            LEFT JOIN chat_preferences cp
                ON cp.chat_id = dq.chat_id AND cp.account_phone = dq.account_phone
            WHERE {' AND '.join(where)}
            ORDER BY dq.file_size ASC NULLS LAST, dq.created_at DESC, dq.id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def ensure_chat_preferences_table(conn) -> None:
    """Valida que exista la tabla chat_preferences (sin crearla).

    La creación de esquema debe hacerse en PostgreSQL (init_db.sql).
    """
    if _schema_checks["chat_preferences_table"]:
        return
    if not _table_exists(conn, "chat_preferences"):
        raise RuntimeError(
            "Falta la tabla 'chat_preferences'. El esquema debe inicializarse en PostgreSQL (postgres/init_db.sql)."
        )
    _schema_checks["chat_preferences_table"] = True


def ensure_download_queue_account_phone(conn) -> None:
    """Valida que exista la columna account_phone en download_queue (sin alterarla)."""
    if _schema_checks["download_queue_account_phone"]:
        return
    if not _table_exists(conn, "download_queue"):
        raise RuntimeError(
            "Falta la tabla 'download_queue'. El esquema debe inicializarse en PostgreSQL (postgres/init_db.sql)."
        )
    if not _column_exists(conn, "download_queue", "account_phone"):
        raise RuntimeError(
            "Falta la columna 'download_queue.account_phone'. Actualiza el esquema en PostgreSQL (postgres/init_db.sql) o aplica la migración correspondiente."
        )
    _schema_checks["download_queue_account_phone"] = True


def is_media_download_enabled(conn, chat_id: int, account_phone: str) -> bool:
    """Devuelve True si el chat tiene habilitada la descarga de media (default True)."""
    ensure_chat_preferences_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(media_download_enabled, TRUE) AS enabled
            FROM chat_preferences
            WHERE chat_id = %s AND account_phone = %s
            """,
            (chat_id, account_phone),
        )
        row = cur.fetchone()
    return bool(row["enabled"]) if row else True


def get_downloaded_path_by_unique_id(conn, file_unique_id: Optional[str]) -> Optional[str]:
    """Devuelve una ruta ya descargada para un file_unique_id, si existe."""
    if not file_unique_id:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT path FROM download_queue
            WHERE file_unique_id = %s AND status = 'done' AND path IS NOT NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (file_unique_id,)
        )
        row = cur.fetchone()
    return row["path"] if row else None


def mark_download_in_progress(conn, row_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE download_queue
            SET status = 'in_progress', attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (row_id,)
        )
    conn.commit()


def mark_download_done(conn, row_id: int, path: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE download_queue
            SET status = 'done', path = %s, error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (path, row_id)
        )
    conn.commit()


def reset_stuck_downloads(conn, max_age_minutes: Optional[int] = 10, account_phone: Optional[str] = None) -> int:
    """Rehidrata descargas en progreso, devolviéndolas a pending.

    Si max_age_minutes es None, rehidrata todas las filas en 'in_progress'.
    Devuelve el número de filas actualizadas.
    """
    with conn.cursor() as cur:
        base = (
            "UPDATE download_queue "
            "SET status = 'pending', updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'in_progress'"
        )
        params = []

        if account_phone:
            base += " AND account_phone = %s"
            params.append(account_phone)

        if max_age_minutes is not None:
            base += " AND updated_at < (CURRENT_TIMESTAMP - (%s * INTERVAL '1 minute'))"
            params.append(int(max_age_minutes))

        cur.execute(base, tuple(params))
        updated = cur.rowcount
    conn.commit()
    return updated


def mark_download_failed(conn, row_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE download_queue
            SET status = 'failed', error = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (error[:500], row_id)
        )
    conn.commit()


def mark_message_unrecoverable(conn, chat_id: int, msg_id: int, account_phone: str, reason: str = "unrecoverable") -> None:
    """Inserta un placeholder para cerrar gaps de mensajes que Telegram no entrega."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages (
                msg_id, chat_id, sender_id, text, media_type, media_file_path,
                is_forward, forward_sender_id, reply_to_msg_id, edit_date,
                views, forwards, pin, silent, is_post, ttl_period, topic_id,
                has_log, created_at, account_phone
            ) VALUES (%s, %s, NULL, %s, %s, NULL,
                      FALSE, NULL, NULL, NULL,
                      NULL, NULL, FALSE, FALSE, FALSE, NULL, NULL,
                      FALSE, CURRENT_TIMESTAMP, %s)
            ON CONFLICT (chat_id, msg_id, account_phone) DO NOTHING
            """,
            (msg_id, chat_id, f"__UNRECOVERABLE__:{reason}", "unrecoverable", account_phone),
        )
    conn.commit()


def get_chat_gaps(conn, chat_id: int, account_phone: str, limit: int = 1000) -> list:
    """
    Obtiene los gaps (mensajes faltantes) en un chat para una cuenta específica.
    Retorna una lista de rangos (min_id, max_id) donde faltan mensajes.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH message_sequence AS (
                SELECT 
                    msg_id,
                    LAG(msg_id) OVER (ORDER BY msg_id) as prev_msg_id
                FROM messages
                WHERE chat_id = %s AND account_phone = %s
                ORDER BY msg_id
            )
            SELECT 
                prev_msg_id + 1 as gap_start,
                msg_id - 1 as gap_end,
                (msg_id - prev_msg_id - 1) as gap_size
            FROM message_sequence
            WHERE prev_msg_id IS NOT NULL 
              AND msg_id - prev_msg_id > 1
            ORDER BY gap_size DESC
            LIMIT %s
            """,
            (chat_id, account_phone, limit)
        )
        return cur.fetchall()
