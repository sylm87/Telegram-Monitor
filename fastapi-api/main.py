import json
import os
from typing import List, Optional, Dict, Any

import psycopg2
import psycopg2.extras
from psycopg2 import pool
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.environ.get("ENV_FILE", None), env_prefix="")

    # Host suele ser el nombre del servicio en Docker.
    db_host: str = Field(default="postgres", validation_alias=AliasChoices("DB_HOST", "POSTGRES_HOST"))

    # Para el resto preferimos POSTGRES_* en .env, con compatibilidad hacia atrás con DB_*.
    db_port: int = Field(default=5432, validation_alias=AliasChoices("DB_PORT", "POSTGRES_PORT"))
    db_name: str = Field(default="telegram_monitor", validation_alias=AliasChoices("POSTGRES_DB", "DB_NAME"))
    db_user: str = Field(default="telegram", validation_alias=AliasChoices("POSTGRES_USER", "DB_USER"))
    db_password: str = Field(
        default="",
        validation_alias=AliasChoices("POSTGRES_PASSWORD", "DB_PASSWORD"),
    )

    media_root: str = Field(default="/app/media_downloads", validation_alias=AliasChoices("MEDIA_ROOT", "TG_MEDIA_DIR"))

    # CORS: acepta "*", CSV ("https://a.com,https://b.com") o JSON ("[\"https://a.com\", ...]")
    cors_allow_origins: str = Field(
        default="*",
        validation_alias=AliasChoices("CORS_ALLOW_ORIGINS", "CORS_ORIGINS", "ALLOW_ORIGINS"),
    )


def parse_cors_allow_origins(value: str) -> List[str]:
    raw = (value or "").strip()
    if raw == "" or raw == "*":
        return ["*"]

    # Permite lista JSON para evitar problemas con comas/espacios
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                origins = [str(x).strip() for x in parsed if str(x).strip()]
                return origins or ["*"]
        except Exception:
            pass

    # CSV: separar por coma
    origins = [part.strip() for part in raw.split(",") if part.strip()]
    return origins or ["*"]


class QueueStats(BaseModel):
    status: str
    total: int


class QueueAging(BaseModel):
    status: str
    older_10m: int


class Chat(BaseModel):
    chat_id: int
    account_phone: Optional[str]
    title: Optional[str]
    chat_type: Optional[str]
    last_msg: Optional[str]
    media_download_enabled: Optional[bool] = True


class DownloadItem(BaseModel):
    id: int
    chat_id: int
    msg_id: int
    account_phone: Optional[str] = None
    sender_id: Optional[int] = None
    media_type: Optional[str] = None
    file_name: Optional[str] = None
    status: str
    path: Optional[str]
    updated_at: Optional[str]


class MessageItem(BaseModel):
    msg_id: int
    chat_id: int
    account_phone: Optional[str]
    sender_id: Optional[int]
    text: Optional[str]
    created_at: Optional[str]
    media_type: Optional[str]
    media_file_path: Optional[str]
    sender_username: Optional[str] = None
    sender_first_name: Optional[str] = None
    sender_last_name: Optional[str] = None
    sender_is_bot: Optional[bool] = None
    chat_title: Optional[str] = None
    chat_type: Optional[str] = None


class ChatSettingsUpdate(BaseModel):
    media_download_enabled: bool


class MessageWithLog(BaseModel):
    msg_id: int
    chat_id: int
    account_phone: Optional[str]
    sender_id: Optional[int]
    sender_username: Optional[str]
    sender_first_name: Optional[str]
    sender_last_name: Optional[str]
    text: Optional[str]
    created_at: Optional[str]
    media_type: Optional[str]
    media_file_path: Optional[str]
    log: List[Dict[str, Any]] = []


settings = Settings()
app = FastAPI(title="Telegram Monitor API", version="0.1.0")

_cors_origins = parse_cors_allow_origins(settings.cors_allow_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_pool = None


def get_pool():
    global _pool
    if _pool is None:
        if settings.db_password == "":
            raise RuntimeError(
                "Falta configurar POSTGRES_PASSWORD/DB_PASSWORD (no hay valor por defecto por seguridad)."
            )
        _pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _pool


def get_conn():
    pool = get_pool()
    conn = pool.getconn()
    return conn


async def db_dep():
    conn = get_conn()
    try:
        yield conn
    finally:
        get_pool().putconn(conn)


@app.get("/media")
async def serve_media(path: str):
    """Devuelve archivos de media asegurando que estén bajo MEDIA_ROOT."""
    normalized = os.path.normpath(path)
    candidate = (
        normalized
        if os.path.isabs(normalized)
        else os.path.normpath(os.path.join(settings.media_root, normalized))
    )

    media_root = os.path.normpath(settings.media_root)
    try:
        base = os.path.commonpath([candidate, media_root])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid media path")

    if base != media_root:
        raise HTTPException(status_code=400, detail="Invalid media path")
    if not os.path.exists(candidate):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(candidate)


@app.on_event("startup")
async def startup_event():
    # Ensure pool is created and schema exists (sin DDL en runtime).
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s) AS reg", ("public.chat_preferences",))
            row = cur.fetchone()
            if not row or not row.get("reg"):
                raise RuntimeError(
                    "Falta la tabla 'chat_preferences'. El esquema debe inicializarse en PostgreSQL (postgres/init_db.sql)."
                )
    finally:
        pool.putconn(conn)


@app.on_event("shutdown")
async def shutdown_event():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/stats/queue", response_model=dict)
async def queue_stats(conn=Depends(db_dep)):
    # Nota: queremos que el contador de 'pending' refleje solo las descargas
    # procesables. Si un chat tiene media desactivada (chat_preferences.media_download_enabled = FALSE)
    # esas filas 'pending' siguen existiendo en download_queue, pero el worker no las consumirá.
    # Aquí las excluimos del conteo de 'pending' para que el panel muestre la cola efectiva.

    with conn.cursor() as cur:
        # Pending TOTAL (sin filtrar por preferencias), útil para UI
        cur.execute("SELECT COUNT(*) AS total FROM download_queue WHERE status = 'pending';")
        pending_total = int(cur.fetchone()["total"])

        cur.execute(
            """
            SELECT dq.status, COUNT(*) AS total
            FROM download_queue dq
            LEFT JOIN chat_preferences cp
              ON cp.chat_id = dq.chat_id AND cp.account_phone = dq.account_phone
            WHERE dq.status <> 'pending'
               OR COALESCE(cp.media_download_enabled, TRUE) = TRUE
            GROUP BY dq.status
            ORDER BY dq.status;
            """
        )
        stats = cur.fetchall()

        cur.execute(
            """
            SELECT dq.status, COUNT(*) AS older_10m
            FROM download_queue dq
            LEFT JOIN chat_preferences cp
              ON cp.chat_id = dq.chat_id AND cp.account_phone = dq.account_phone
            WHERE dq.updated_at < NOW() - INTERVAL '10 minutes'
              AND (
                dq.status <> 'pending'
                OR COALESCE(cp.media_download_enabled, TRUE) = TRUE
              )
            GROUP BY dq.status
            ORDER BY dq.status;
            """
        )
        aging = cur.fetchall()

    return {"stats": stats, "aging": aging, "pending_total": pending_total}


@app.get("/chats", response_model=List[Chat])
async def list_chats(
    account: Optional[str] = Query(None, description="Filtro por línea"),
    chat_id: Optional[int] = Query(None, description="Filtro por ID de chat"),
    chat_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Buscar en título/username"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn=Depends(db_dep),
):
    clauses = []
    params = []
    if account:
        clauses.append("c.account_phone = %s")
        params.append(account)
    if chat_id is not None:
        clauses.append("c.chat_id = %s")
        params.append(chat_id)
    if chat_type:
        clauses.append("c.chat_type = %s")
        params.append(chat_type)
    if search:
        clauses.append("(lower(c.title) LIKE %s OR lower(c.username) LIKE %s)")
        like = f"%{search.lower()}%"
        params.extend([like, like])
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"""
        SELECT c.chat_id, c.account_phone, c.title, c.chat_type,
               TO_CHAR(MAX(m.created_at), 'YYYY-MM-DD HH24:MI:SS') AS last_msg,
               COALESCE(p.media_download_enabled, TRUE) AS media_download_enabled
        FROM chats c
        LEFT JOIN messages m ON m.chat_id = c.chat_id AND m.account_phone = c.account_phone
        LEFT JOIN chat_preferences p ON p.chat_id = c.chat_id AND p.account_phone = c.account_phone
        {where_sql}
        GROUP BY c.chat_id, c.account_phone, c.title, c.chat_type, p.media_download_enabled
        ORDER BY last_msg DESC NULLS LAST
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return rows


@app.get("/chats/{chat_id}/messages", response_model=Dict[str, Any])
async def list_chat_messages(
    chat_id: int,
    account: str = Query(..., description="Línea (account_phone)"),
    before_id: Optional[int] = Query(None, description="msg_id límite superior (exclusivo)"),
    after_id: Optional[int] = Query(None, description="msg_id límite inferior (exclusivo) - para obtener mensajes nuevos"),
    around_id: Optional[int] = Query(None, description="msg_id central - carga mensajes alrededor de este ID"),
    limit: int = Query(100, le=1000),
    include_logs: bool = Query(True),
    conn=Depends(db_dep),
):
    # Si se especifica around_id, cargar mensajes alrededor de ese ID
    if around_id:
        # Cargar limit/2 mensajes antes y limit/2 después del ID objetivo
        half_limit = limit // 2
        
        clauses = ["m.chat_id = %s", "m.account_phone = %s"]
        params = [chat_id, account]
        
        where_sql = "WHERE " + " AND ".join(clauses)
        
        # Obtener mensajes antes del ID (incluyendo el mensaje objetivo)
        sql_before = f"""
            SELECT m.msg_id, m.chat_id, m.account_phone, m.sender_id, m.text, m.media_type, m.media_file_path,
                   TO_CHAR(m.created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at,
                   s.username AS sender_username, s.first_name AS sender_first_name, s.last_name AS sender_last_name
            FROM messages m
            LEFT JOIN senders s ON m.sender_id = s.user_id AND m.account_phone = s.account_phone
            {where_sql} AND m.msg_id <= %s
            AND ((m.media_type IS NULL OR m.media_type != 'unrecoverable') OR m.msg_id = %s)
            ORDER BY m.msg_id DESC
            LIMIT %s
        """
        
        # Obtener mensajes después del ID
        sql_after = f"""
            SELECT m.msg_id, m.chat_id, m.account_phone, m.sender_id, m.text, m.media_type, m.media_file_path,
                   TO_CHAR(m.created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at,
                   s.username AS sender_username, s.first_name AS sender_first_name, s.last_name AS sender_last_name
            FROM messages m
            LEFT JOIN senders s ON m.sender_id = s.user_id AND m.account_phone = s.account_phone
            {where_sql} AND m.msg_id > %s
            AND ((m.media_type IS NULL OR m.media_type != 'unrecoverable') OR m.msg_id = %s)
            ORDER BY m.msg_id ASC
            LIMIT %s
        """
        
        messages = []
        with conn.cursor() as cur:
            # Obtener mensajes antes (incluyendo el objetivo)
            cur.execute(sql_before, params + [around_id, around_id, half_limit])
            messages_before = cur.fetchall()
            
            # Obtener mensajes después
            cur.execute(sql_after, params + [around_id, around_id, half_limit])
            messages_after = cur.fetchall()
            
            # Combinar y devolver en DESC (newest first) como el resto del API
            # messages_before ya está en DESC
            # messages_after está en ASC, hay que invertirlo y ponerlo ANTES de messages_before
            messages = list(reversed(messages_after)) + messages_before
            
        print(f"DEBUG around_id={around_id}: {len(messages_before)} before + {len(messages_after)} after = {len(messages)} total")
        
    else:
        # Lógica original con before_id/after_id
        clauses = ["m.chat_id = %s", "m.account_phone = %s"]
        params = [chat_id, account]
        if before_id:
            clauses.append("m.msg_id < %s")
            params.append(before_id)
        if after_id:
            clauses.append("m.msg_id > %s")
            params.append(after_id)
        
        # Siempre filtrar mensajes unrecoverable a nivel de SQL
        clauses.append("(m.media_type IS NULL OR m.media_type != 'unrecoverable')")
        
        where_sql = "WHERE " + " AND ".join(clauses)
        
        sql = f"""
            SELECT m.msg_id, m.chat_id, m.account_phone, m.sender_id, m.text, m.media_type, m.media_file_path,
                   TO_CHAR(m.created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at,
                   s.username AS sender_username, s.first_name AS sender_first_name, s.last_name AS sender_last_name
            FROM messages m
            LEFT JOIN senders s ON m.sender_id = s.user_id AND m.account_phone = s.account_phone
            {where_sql}
            ORDER BY m.msg_id DESC
            LIMIT %s
        """
        params.append(limit)
        messages = []
        with conn.cursor() as cur:
            # Debug logging
            print(f"DEBUG SQL: {sql}")
            print(f"DEBUG PARAMS: {params}")
            cur.execute(sql, params)
            messages = cur.fetchall()
            print(f"DEBUG RESULTS: {len(messages)} messages")

    if include_logs and messages:
        msg_ids = [m["msg_id"] for m in messages]
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT telegram_msg_id AS msg_id, chat_id, text, media_type,
                       TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at
                FROM message_log
                WHERE chat_id = %s AND telegram_msg_id = ANY(%s)
                ORDER BY created_at DESC
                """,
                (chat_id, msg_ids),
            )
            logs = cur.fetchall()
        log_map = {}
        for log in logs:
            log_map.setdefault(log["msg_id"], []).append(log)
        for m in messages:
            m["log"] = log_map.get(m["msg_id"], [])
    
    # Verificar si hay más mensajes disponibles
    # Necesitamos buscar el siguiente mensaje válido (no unrecoverable)
    more_available = False
    if messages:
        last_msg_id = messages[-1]["msg_id"]
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM messages m
                WHERE m.chat_id = %s AND m.account_phone = %s 
                  AND m.msg_id < %s
                  AND (m.media_type IS NULL OR m.media_type != 'unrecoverable')
                LIMIT 1
                """,
                (chat_id, account, last_msg_id)
            )
            result = cur.fetchone()
            more_available = result["count"] > 0
    
    return {"messages": messages, "more": more_available}


@app.patch("/chats/{chat_id}/settings")
async def update_chat_settings(chat_id: int, body: ChatSettingsUpdate, account: Optional[str] = Query(None), conn=Depends(db_dep)):
    if not account:
        raise HTTPException(status_code=400, detail="account is required")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_preferences (chat_id, account_phone, media_download_enabled)
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id, account_phone)
            DO UPDATE SET media_download_enabled = EXCLUDED.media_download_enabled
            """,
            (chat_id, account, body.media_download_enabled),
        )
        conn.commit()
    return {"chat_id": chat_id, "account": account, "media_download_enabled": body.media_download_enabled}


@app.get("/downloads", response_model=List[DownloadItem])
async def list_downloads(
    status: Optional[str] = Query(None),
    chat_id: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn=Depends(db_dep),
):
    clauses = []
    params = []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if chat_id:
        clauses.append("chat_id = %s")
        params.append(chat_id)
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"""
        SELECT dq.id,
               dq.chat_id,
               dq.msg_id,
               m.account_phone,
               m.sender_id,
               m.media_type,
               m.media_file_path,
               dq.status,
               dq.path,
               TO_CHAR(dq.updated_at, 'YYYY-MM-DD HH24:MI:SS') AS updated_at
        FROM download_queue dq
        LEFT JOIN LATERAL (
            SELECT account_phone, sender_id, media_type, media_file_path
            FROM messages
            WHERE chat_id = dq.chat_id AND msg_id = dq.msg_id
            ORDER BY account_phone
            LIMIT 1
        ) m ON TRUE
        {where_sql}
        ORDER BY dq.updated_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    # Fallback: si no hay account_phone pero el path la incluye (/app/media_downloads/<account>/<chat>/...)
    for r in rows:
        try:
            if (not r.get("account_phone")) and r.get("path"):
                parts = str(r["path"]).split("/")
                # ['', 'app', 'media_downloads', '+3467...', '-100...', ...]
                if len(parts) >= 4 and parts[3].startswith("+"):
                    r["account_phone"] = parts[3]
        except Exception:
            pass

        try:
            # file_name: prefer path basename; else fallback to media_file_path basename
            p = r.get("path") or r.get("media_file_path")
            if p and not r.get("file_name"):
                r["file_name"] = os.path.basename(str(p))
        except Exception:
            pass

        # El response_model no incluye media_file_path: lo eliminamos si viene del SQL
        if "media_file_path" in r:
            r.pop("media_file_path", None)

    return rows


@app.get("/chats/{chat_id}/media", response_model=List[DownloadItem])
async def list_chat_media(
    chat_id: int,
    status: Optional[str] = Query("done"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    conn=Depends(db_dep),
):
    clauses = ["chat_id = %s"]
    params = [chat_id]
    if status:
        clauses.append("status = %s")
        params.append(status)
    where_sql = "WHERE " + " AND ".join(clauses)
    sql = f"""
        SELECT dq.id,
               dq.chat_id,
               dq.msg_id,
               m.account_phone,
               m.sender_id,
               m.media_type,
               m.media_file_path,
               dq.status,
               dq.path,
               TO_CHAR(dq.updated_at, 'YYYY-MM-DD HH24:MI:SS') AS updated_at
        FROM download_queue dq
        LEFT JOIN LATERAL (
            SELECT account_phone, sender_id, media_type, media_file_path
            FROM messages
            WHERE chat_id = dq.chat_id AND msg_id = dq.msg_id
            ORDER BY account_phone
            LIMIT 1
        ) m ON TRUE
        {where_sql}
        ORDER BY dq.updated_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    for r in rows:
        try:
            if (not r.get("account_phone")) and r.get("path"):
                parts = str(r["path"]).split("/")
                if len(parts) >= 4 and parts[3].startswith("+"):
                    r["account_phone"] = parts[3]
        except Exception:
            pass

        try:
            p = r.get("path") or r.get("media_file_path")
            if p and not r.get("file_name"):
                r["file_name"] = os.path.basename(str(p))
        except Exception:
            pass

        if "media_file_path" in r:
            r.pop("media_file_path", None)

    return rows


@app.get("/search/messages", response_model=List[MessageItem])
async def search_messages(
    q: Optional[str] = Query(None, description="texto a buscar"),
    account: Optional[str] = Query(None, description="Número de cuenta"),
    chat_id: Optional[int] = Query(None, description="ID del chat"),
    sender_id: Optional[int] = Query(None, description="ID del remitente"),
    sender_username: Optional[str] = Query(None, description="Username del remitente"),
    chat_type: Optional[str] = Query(None, description="Tipo de chat (channel, group, private)"),
    media_only: Optional[bool] = Query(False, description="Solo mensajes con media"),
    media_type: Optional[str] = Query(None, description="Tipo de media específico"),
    date_from: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    limit: int = Query(50, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(db_dep),
):
    clauses = []
    params = []
    
    # Búsqueda de texto
    if q:
        clauses.append("m.text ILIKE %s")
        params.append(f"%{q}%")
    
    # Filtros específicos
    if account:
        clauses.append("m.account_phone = %s")
        params.append(account)
    if chat_id:
        clauses.append("m.chat_id = %s")
        params.append(chat_id)
    if sender_id:
        clauses.append("m.sender_id = %s")
        params.append(sender_id)
    if sender_username:
        clauses.append("s.username ILIKE %s")
        params.append(f"%{sender_username}%")
    if chat_type:
        clauses.append("c.chat_type = %s")
        params.append(chat_type)
    if media_only:
        clauses.append("m.media_file_path IS NOT NULL")
    if media_type:
        clauses.append("m.media_type = %s")
        params.append(media_type)
    
    # Filtrar mensajes unrecoverable
    clauses.append("(m.media_type IS NULL OR m.media_type != 'unrecoverable')")
    
    # Filtros de fecha
    if date_from:
        clauses.append("m.created_at >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("m.created_at <= %s")
        params.append(date_to)
    
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    
    sql = f"""
        SELECT m.msg_id, m.chat_id, m.account_phone, m.sender_id, m.text, m.media_type, m.media_file_path,
               TO_CHAR(m.created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at,
               s.username AS sender_username, s.first_name AS sender_first_name, s.last_name AS sender_last_name,
               s.is_bot AS sender_is_bot,
               c.title AS chat_title, c.chat_type
        FROM messages m
        LEFT JOIN senders s ON m.sender_id = s.user_id AND m.account_phone = s.account_phone
        LEFT JOIN chats c ON m.chat_id = c.chat_id AND m.account_phone = c.account_phone
        {where_sql}
        ORDER BY m.created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    
    return rows
