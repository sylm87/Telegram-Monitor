import argparse
import asyncio
import logging
import os
import re
import sys
import unicodedata
import mimetypes
import threading
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession, SQLiteSession
from telethon.tl.types import (
    User,
    Chat,
    Channel,
    DocumentAttributeAudio,
    DocumentAttributeVideo,
    DocumentAttributeAnimated,
    DocumentAttributeSticker,
)
from telethon.errors import SessionPasswordNeededError

from .db import (
    get_db_connection, close_db_connection, insert_or_update_chat, insert_or_update_sender,
    insert_message, insert_reactions, insert_entities, update_message,
    insert_message_log, get_max_message_id_in_chat, get_chat_gaps,
    enqueue_download, fetch_pending_downloads, fetch_recent_pending_downloads, get_downloaded_path_by_unique_id,
    mark_download_in_progress, mark_download_done, mark_download_failed,
    reset_stuck_downloads, mark_message_unrecoverable,
    is_media_download_enabled,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
HISTORIC_GAP_THRESHOLD = int(os.environ.get("LISTENER_HISTORIC_GAP_THRESHOLD", "10"))

# File handler para SOLO errores/avisos persistentes (WARNING, ERROR, CRITICAL)
_error_log_file = os.environ.get("TG_ERROR_LOG", "/output/err-logs/tel-cli.error.log")
os.makedirs(os.path.dirname(_error_log_file), exist_ok=True)
if not any(isinstance(h, logging.FileHandler) and h.baseFilename == _error_log_file for h in logger.handlers):
    fh_error = logging.FileHandler(_error_log_file, encoding="utf-8")
    fh_error.setLevel(logging.WARNING)  # SOLO WARNING, ERROR, CRITICAL
    fh_error.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
    logger.addHandler(fh_error)

# File handler para salida estándar (INFO y superiores)
_output_log_file = os.environ.get("TG_OUTPUT_LOG", "/output/out-logs/tel-cli.output.log")
os.makedirs(os.path.dirname(_output_log_file), exist_ok=True)
if not any(isinstance(h, logging.FileHandler) and h.baseFilename == _output_log_file for h in logger.handlers):
    fh_output = logging.FileHandler(_output_log_file, encoding="utf-8")
    fh_output.setLevel(logging.INFO)  # INFO, WARNING, ERROR, CRITICAL
    fh_output.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
    logger.addHandler(fh_output)


# Loggers por thread (separados)
def _create_thread_logger(thread_name: str):
    """Crea un logger dedicado para un thread con su propio fichero"""
    thread_logger = logging.getLogger(f"telegram.{thread_name}")
    thread_logger.setLevel(logging.INFO)
    thread_logger.propagate = False
    
    # Fichero del thread
    out_logs_dir = "/output/out-logs"
    os.makedirs(out_logs_dir, exist_ok=True)
    log_file = f"{out_logs_dir}/tel-cli.{thread_name.lower()}.log"
    
    # Remover handlers anteriores si existen
    thread_logger.handlers.clear()
    
    # File handler para este thread
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
    thread_logger.addHandler(fh)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
    thread_logger.addHandler(ch)
    
    return thread_logger


# Loggers dedicados para diferentes tipos de eventos
logger_live = _create_thread_logger("live")
logger_catchup = _create_thread_logger("catchup")
logger_download = _create_thread_logger("download")

# Cliente compartido para todos los threads (DEPRECATED - cada thread debe crear su propio)
_shared_client = None
_shared_client_lock = threading.Lock()


def build_client() -> TelegramClient:
    """
    Construye cliente de Telegram con FileSession.
    Intenta cargar sesión desde archivo, si no existe la crea desde StringSession.
    FileSession es necesario para que funcionen los event handlers.
    """
    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    
    if not api_id or not api_hash:
        raise RuntimeError("Faltan TG_API_ID o TG_API_HASH en el entorno (.env)")

    session_file = "/app/me.session"
    session_base = "/app/me"  # Telethon creará /app/me.session

    # 1) Si no existe el archivo y tenemos TG_SESSION_STRING, materializarlo a FileSession
    if not os.path.exists(session_file):
        session_string = os.environ.get("TG_SESSION_STRING")
        if session_string:
            logger.info("🧩 TG_SESSION_STRING detectado: generando /app/me.session antes de conectar...")
            file_session = SQLiteSession(session_base)
            string_session = StringSession(session_string)

            # Copiar parámetros de DC/autenticación
            file_session.set_dc(string_session.dc_id, string_session.server_address, string_session.port)
            file_session.auth_key = string_session.auth_key

            # Copiar takeout_id si existiera
            if hasattr(string_session, "takeout_id") and hasattr(file_session, "takeout_id"):
                file_session.takeout_id = getattr(string_session, "takeout_id")

            file_session.save()

            if os.path.exists(session_file):
                logger.info("✅ /app/me.session creado desde TG_SESSION_STRING")
            else:
                logger.warning("⚠️ No se pudo verificar la creación de /app/me.session; se intentará igualmente")

    # 2) Usar siempre FileSession (necesario para persistencia y event handlers)
    if os.path.exists(session_file):
        logger.info(f"✅ Usando FileSession: {session_file}")
        session = session_base
    else:
        logger.info("⚠️ No hay /app/me.session y no hay TG_SESSION_STRING válido; se creará nueva sesión (requiere login interactivo)")
        session = session_base

    client = TelegramClient(session, int(api_id), api_hash)
    return client


async def iter_all_dialogs(client: TelegramClient):
    # Si Telethon está desconectado, intentar reconectar antes de iterar.
    # Esto evita spam de logs y permite recuperar tras microcortes de red.
    if not client.is_connected():
        try:
            await client.connect()
        except Exception as e:
            logger.warning(f"  No se pudo reconectar a Telegram antes de listar diálogos: {e}")
            return

    try:
        logger.info("  Iterando diálogos sin filtro de folder...")
        count = 0
        async for dialog in client.iter_dialogs():
            count += 1
            yield dialog
        logger.info(f"  Total de diálogos sin filtro: {count}")
    except Exception as e:
        logger.warning(f"  No se pudieron obtener todos los diálogos: {e}")
        # Fallback mínimo a principal y archivados
        for folder in (0, 1):
            logger.info(f"  Iterando diálogos con folder={folder}...")
            count = 0
            try:
                async for dialog in client.iter_dialogs(folder=folder):
                    count += 1
                    yield dialog
                logger.info(f"  Diálogos encontrados en folder={folder}: {count}")
            except Exception as e2:
                logger.warning(f"  No se pudieron obtener diálogos (folder={folder}): {e2}")


async def _ensure_connected(client: TelegramClient, sleep_seconds: int = 10) -> bool:
    if client.is_connected():
        return True
    try:
        await client.connect()
        return client.is_connected()
    except Exception as e:
        logger.warning(f"Cliente desconectado y no se pudo reconectar (reintento en {sleep_seconds}s): {e}")
        await asyncio.sleep(sleep_seconds)
        return False


def _is_interactive_tty() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:
        return False


async def ensure_login(client: TelegramClient, phone: Optional[str]) -> None:
    await client.connect()
    if await client.is_user_authorized():
        return

    if not phone:
        raise RuntimeError("Falta TG_PHONE para iniciar sesión por primera vez")

    # Si no hay TTY (p.ej. contenedor sin attach), no podemos pedir inputs.
    # En lugar de hacer que el proceso caiga con EOFError y reinicie en bucle,
    # fallamos con un mensaje claro.
    if not _is_interactive_tty():
        raise RuntimeError(
            "Sesión no autorizada y no hay TTY para login interactivo. "
            "Ejecuta el flujo de init (telegram-init) para regenerar la sesión y vuelve a arrancar."
        )

    logger.info("Solicitando código de verificación a Telegram...")
    await client.send_code_request(phone)
    try:
        code = input("Código recibido por Telegram: ")
    except EOFError as exc:
        raise RuntimeError("Entrada no disponible para introducir el código (EOF).") from exc

    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        try:
            password = input("Contraseña 2FA: ")
        except EOFError as exc:
            raise RuntimeError("Entrada no disponible para introducir la contraseña 2FA (EOF).") from exc
        await client.sign_in(password=password)


async def list_dialogs(client: TelegramClient, limit: int) -> None:
    logger.info("Listando diálogos...")
    async for dialog in client.iter_dialogs(limit=limit):
        entity = dialog.entity
        name = dialog.name or "(sin nombre)"
        username = getattr(entity, "username", None) or "-"

        if isinstance(entity, User):
            tipo = "user"
        elif isinstance(entity, Chat):
            tipo = "group"
        elif isinstance(entity, Channel):
            # Distinguimos supergrupos vs canales broadcast
            tipo = "supergroup" if getattr(entity, "megagroup", False) else "channel"
        else:
            tipo = "unknown"

        username_fmt = f"@{username}" if username != "-" else "-"
        print(f"{dialog.id} | {tipo} | {username_fmt} | {name}")


def _sanitize_label(text: str) -> str:
    allowed = "-_. "
    return "".join(c for c in text if c.isalnum() or c in allowed).strip().replace(" ", "_")


INVALID_FS_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"}
WINDOWS_RESERVED_NAMES.update({f"COM{i}" for i in range(1, 10)})
WINDOWS_RESERVED_NAMES.update({f"LPT{i}" for i in range(1, 10)})
MAX_FILENAME_LENGTH = 180


def _sanitize_filename(name: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Sanitize file names for cross-platform safety."""
    normalized = unicodedata.normalize("NFC", name or "").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    cleaned = INVALID_FS_CHARS_RE.sub("-", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")

    if not cleaned:
        cleaned = "file"

    base, ext = os.path.splitext(cleaned)
    ext = ext[:20]  # avoid absurd extensions
    base = base[: max(1, max_length - len(ext))]

    if base.upper() in WINDOWS_RESERVED_NAMES:
        base = f"{base}_"

    return f"{base}{ext}" if base else f"file{ext}"


def _guess_extension_from_mime(mime_type: Optional[str]) -> Optional[str]:
    if not mime_type:
        return None
    guessed = mimetypes.guess_extension(mime_type)
    return guessed if guessed else None


def _classify_media_type(message) -> str:
    doc = getattr(message, "document", None)
    if getattr(message, "photo", None):
        return "photo"
    if doc:
        attrs = getattr(doc, "attributes", []) or []
        for attr in attrs:
            if isinstance(attr, DocumentAttributeSticker):
                return "sticker"
            if isinstance(attr, DocumentAttributeAudio):
                return "voice" if getattr(attr, "voice", False) else "audio"
            if isinstance(attr, DocumentAttributeVideo):
                return "video"
            if isinstance(attr, DocumentAttributeAnimated):
                return "animation"
        mime_type = getattr(doc, "mime_type", "") or ""
        if mime_type.startswith("video/"):
            return "video"
        if mime_type.startswith("audio/"):
            return "audio"
        return "document"
    if getattr(message, "voice", None):
        return "voice"
    if getattr(message, "media", None):
        return type(message.media).__name__ or "other"
    return "other"


def _infer_media_filename(message, media_type: str, file_unique_id: Optional[str] = None) -> str:
    file_obj = getattr(message, "file", None)
    name = getattr(file_obj, "name", None) if file_obj else None
    ext = None

    if not name:
        ext = getattr(file_obj, "ext", None) if file_obj else None
        if not ext:
            ext = _guess_extension_from_mime(getattr(file_obj, "mime_type", None) if file_obj else None)
        if not ext and media_type == "voice":
            ext = ".ogg"
        if not ext and media_type == "sticker":
            ext = ".webp"
        safe_ext = ext if ext and ext.startswith(".") else (f".{ext}" if ext else "")
        # Use file_unique_id if available to prevent overwriting unique files
        if file_unique_id:
            name = f"{media_type or 'file'}_{file_unique_id}" + safe_ext
        else:
            name = f"{media_type or 'file'}_{getattr(message, 'id', 'unknown')}" + safe_ext

    return _sanitize_filename(name)


def _media_base_dir(media_dir: Optional[str]) -> str:
    base = media_dir or os.environ.get("TG_MEDIA_DIR") or "media_downloads"
    phone = os.environ.get("TG_PHONE", "default")
    return os.path.join(base, phone)


def _write_chat_metadata(chat, base_dir: str) -> None:
    chat_id = getattr(chat, "id", None)
    if chat_id is None:
        return
    metadata = {
        "chat_id": chat_id,
        "title": getattr(chat, "title", None),
        "username": getattr(chat, "username", None),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    path = os.path.join(base_dir, str(chat_id), ".metadata.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.warning(f"No se pudo escribir metadata de chat {chat_id}")


async def _catch_up_chat_background(client: TelegramClient, chat_id: int, download: bool, media_dir: Optional[str], max_mb: Optional[int], account_phone: str = None) -> None:
    """Lanza catch-up de forma desacoplada del listener."""
    try:
        await catch_up_chat(client, str(chat_id), download=download, media_dir=media_dir, max_mb=max_mb, account_phone=account_phone)
    except Exception:
        logger.exception(f"Error en catch-up automático para chat {chat_id}")


def _state_path() -> str:
    return os.environ.get("TG_STATE_FILE", "state.json")


def _load_state() -> dict:
    path = _state_path()
    if os.path.exists(path):
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    import json
    path = _state_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _update_last_id(state: dict, chat_id: int, message_id: int) -> None:
    key = str(chat_id)
    prev = state.get(key, {}).get("last_id", 0)
    if message_id > prev:
        state[key] = {"last_id": message_id}


async def _download_media_task(message, chat, media_dir: Optional[str], max_mb: Optional[int]) -> Optional[str]:
    """Descarga media en segundo plano con nombres saneados y rutas por chat_id/tipo."""
    try:
        file_size = None
        if getattr(message, "file", None) and hasattr(message.file, "size"):
            file_size = message.file.size
        elif getattr(message, "media", None) and hasattr(message.media, "size"):
            file_size = message.media.size

        if max_mb is not None and file_size is not None:
            limit_bytes = max_mb * 1024 * 1024
            if file_size > limit_bytes:
                logger.info(
                    f"  ⊘ Media saltada (>{max_mb}MB): msg_id={message.id}, size={(file_size/1024/1024):.2f}MB"
                )
                return None

        media_category = _classify_media_type(message)
        base_dir = _media_base_dir(media_dir)
        _write_chat_metadata(chat, base_dir)
        chat_dir = os.path.join(base_dir, str(message.chat_id), media_category)
        os.makedirs(chat_dir, exist_ok=True)

        file_unique_id = getattr(message.file, "unique_id", None) if getattr(message, "file", None) else None
        filename = _infer_media_filename(message, media_category, file_unique_id)
        target_path = os.path.normpath(os.path.join(chat_dir, filename))

        path = await message.download_media(file=target_path)
        if not path:
            logger.info(f"  ✗ No se pudo descargar media de msg_id={message.id}")
            return None

        logger.info(f"  ✓ Descargado msg_id={message.id}: {path}")

        db = get_db_connection()
        try:
            with db.cursor() as cur:
                cur.execute("UPDATE messages SET media_file_path = %s WHERE msg_id = %s AND chat_id = %s", (path, message.id, message.chat_id))
            db.commit()
            return path
        finally:
            close_db_connection(db)
    except Exception as exc:
        logger.warning(f"  ✗ Error descargando media msg_id={getattr(message, 'id', '?')}: {exc}")
        return None


def _get_file_size(message) -> Optional[int]:
    size = None
    if getattr(message, "file", None) and hasattr(message.file, "size"):
        size = message.file.size
    elif getattr(message, "media", None) and hasattr(message.media, "size"):
        size = message.media.size
    return size


async def _enqueue_media_download(message, chat, media_dir: Optional[str], max_mb: Optional[int], account_phone: str = None) -> None:
    if account_phone is None:
        account_phone = os.environ.get("TG_PHONE", "unknown")
        
    # Respeta preferencia de descarga (por defecto True si no existe registro)
    pref_conn = get_db_connection()
    try:
        enabled = is_media_download_enabled(pref_conn, message.chat_id, account_phone)
    finally:
        close_db_connection(pref_conn)
    if not enabled:
        logger.info(f"  ⊘ Media saltada por preferencia deshabilitada: chat={message.chat_id} cuenta={account_phone}")
        return

    file_size = _get_file_size(message)
    if max_mb is not None and file_size is not None and file_size > max_mb * 1024 * 1024:
        logger.info(
            f"  ⊘ Media saltada (>{max_mb}MB): msg_id={message.id}, size={(file_size/1024/1024):.2f}MB"
        )
        return

    chat_label = str(message.chat_id)
    file_unique_id = None
    if getattr(message, "file", None) is not None:
        file_unique_id = getattr(message.file, "unique_id", None)
    db = get_db_connection()
    try:
        existing_path = get_downloaded_path_by_unique_id(db, file_unique_id)
        if existing_path:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE messages SET media_file_path = %s WHERE msg_id = %s AND chat_id = %s AND account_phone = %s",
                    (existing_path, message.id, message.chat_id, account_phone),
                )
            db.commit()
            logger.info(f"  ⊘ Media ya descargada (file_unique_id) reutilizada: {existing_path}")
        else:
            enqueue_download(db, message.id, message.chat_id, chat_label, media_dir, file_size, file_unique_id, account_phone)
    finally:
        close_db_connection(db)


async def _process_queue_item(client: TelegramClient, row: dict, semaphore: asyncio.Semaphore, media_dir: Optional[str], max_mb: Optional[int], download_logger) -> None:
    async with semaphore:
        download_logger.info(f"📥 Iniciando descarga: Chat={row['chat_id']}, MSG#{row['msg_id']}, Queue ID={row['id']}")

        try:
            msg = await client.get_messages(row["chat_id"], ids=row["msg_id"])
            if not msg:
                raise RuntimeError("Mensaje no encontrado para descarga")
            chat = await msg.get_chat()
            chat_name = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(row['chat_id'])
            download_logger.info(f"   Descargando de '{chat_name}' - MSG#{row['msg_id']}")
            path = await _download_media_task(msg, chat, row.get("media_dir") or media_dir, max_mb)
            conn2 = get_db_connection()
            try:
                if path:
                    mark_download_done(conn2, row["id"], path)
                    download_logger.info(f"   ✓ Descarga completada: {path}")
                else:
                    mark_download_failed(conn2, row["id"], "Sin ruta devuelta")
                    download_logger.warning(f"   ✗ Descarga sin ruta devuelta para MSG#{row['msg_id']}")
            finally:
                close_db_connection(conn2)
        except Exception as exc:
            conn3 = get_db_connection()
            try:
                mark_download_failed(conn3, row["id"], str(exc))
                download_logger.error(f"   ❌ Error descargando MSG#{row['msg_id']}: {str(exc)[:100]}")
            finally:
                close_db_connection(conn3)


async def process_download_queue(
    client: TelegramClient,
    media_dir: Optional[str],
    max_mb: Optional[int],
    concurrency: int = 8,
    stop_when_empty: bool = False,
    account_phone: Optional[str] = None,
) -> None:
    """Procesa la cola de descargas con prioridad a mensajes recientes.

    - Concurrencia total: 8 (por defecto).
    - Reserva mínima: 3 slots dedicados a los mensajes más recientes disponibles.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))
    min_recent_slots = 3
    logger_download.info(
        f"🚀 Procesador de descargas iniciado (concurrencia={concurrency}, min_recent_slots={min_recent_slots}, stop_when_empty={stop_when_empty})"
    )
    processed_count = 0

    if account_phone is None:
        account_phone = os.environ.get("TG_PHONE")

    # Rehidratar descargas colgadas en 'in_progress' (al arrancar)
    conn_reset = get_db_connection()
    try:
        reset_count = reset_stuck_downloads(conn_reset, max_age_minutes=None, account_phone=account_phone)
        if reset_count:
            logger_download.warning(f"♻️ Rehidratadas {reset_count} descargas 'in_progress' antiguas a 'pending'")
    finally:
        close_db_connection(conn_reset)

    tasks = set()
    tasks_recent = set()

    while True:
        # Limpia tareas terminadas y contabiliza
        done = {t for t in tasks if t.done()}
        tasks = {t for t in tasks if not t.done()}
        tasks_recent = {t for t in tasks_recent if not t.done()}
        if done:
            processed_count += len(done)
            logger_download.info(f"✓ Tareas completadas en esta iteración: {len(done)} | Total procesadas: {processed_count}")

        # Rellenar hasta la concurrencia deseada
        while len(tasks) < concurrency:
            slots_available = concurrency - len(tasks)
            logger_download.info(f"⚙️ Slots libres: {slots_available}, tareas activas: {len(tasks)}")
            conn = get_db_connection()
            try:
                # Prioridad: mensajes más recientes (mínimo 3 slots dedicados mientras existan)
                recent_deficit = max(0, min_recent_slots - len(tasks_recent))
                recent_slots = min(recent_deficit, concurrency - len(tasks))

                if recent_slots > 0:
                    recent_rows = fetch_recent_pending_downloads(conn, limit=recent_slots, account_phone=account_phone)
                    if not recent_rows:
                        logger_download.info("⏸ No hay pendientes recientes para cubrir slots priorizados")
                    for row in recent_rows:
                        mark_download_in_progress(conn, row["id"])
                        task = asyncio.create_task(
                            _process_queue_item(client, row, semaphore, media_dir, max_mb, logger_download)
                        )
                        tasks.add(task)
                        tasks_recent.add(task)

                # Resto de slots con criterio FIFO clásico
                slots_available = concurrency - len(tasks)
                if slots_available <= 0:
                    break

                rows = fetch_pending_downloads(conn, limit=slots_available, account_phone=account_phone)
                if not rows:
                    logger_download.info(f"⏸ No hay pendientes para ocupar {slots_available} slots libres")
                    break

                if len(rows) < slots_available:
                    logger_download.info(f"↘️ Solo se obtuvieron {len(rows)} pendientes de {slots_available} solicitados")

                for row in rows:
                    mark_download_in_progress(conn, row["id"])
                    task = asyncio.create_task(
                        _process_queue_item(client, row, semaphore, media_dir, max_mb, logger_download)
                    )
                    tasks.add(task)
            finally:
                close_db_connection(conn)

        if tasks:
            # Esperar a que al menos una tarea finalice para mantener flujo continuo
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            continue

        # Si no hay tareas en curso ni pendientes, seguir sondeando indefinidamente
        await asyncio.sleep(3)


async def _process_message(client: TelegramClient, message, download: bool, media_dir: Optional[str], max_mb: Optional[int], logger_live=None, account_phone: str = None) -> Optional[str]:
    if logger_live is None:
        logger_live = logger
    if account_phone is None:
        account_phone = os.environ.get("TG_PHONE", "unknown")
    sender = await message.get_sender()
    sender_id = getattr(sender, "id", None)
    sender_username = getattr(sender, "username", None) if sender else None
    sender_first_name = getattr(sender, "first_name", None) if sender else None
    sender_last_name = getattr(sender, "last_name", None) if sender else None
    sender_is_bot = bool(getattr(sender, "bot", False)) if sender else False
    # Nombre de log tolerante a None
    # Fallback: siempre tener identificador (usa id si no hay username/nombre)
    sender_name = (
        sender_username
        or (sender_first_name if sender_first_name else None)
        or (str(sender_id) if sender_id is not None else "desconocido")
    )
    chat = await message.get_chat()
    chat_username = getattr(chat, "username", None)
    chat_title = getattr(chat, "title", None)
    if chat_title is None and isinstance(chat, User):
        name_parts = [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]
        name_combined = " ".join([p for p in name_parts if p]) or None
        chat_title = name_combined or chat_username
    if chat_title is None:
        chat_title = chat_username or str(message.chat_id)
    chat_name = chat_title
    chat_id = message.chat_id  # Identificador único e inmutable
    gap = None
    
    # Guardar en BD
    db = get_db_connection()
    try:
        previous_max_id = get_max_message_id_in_chat(db, chat_id, account_phone)
        # Determinar tipo de chat
        if isinstance(chat, User):
            chat_type = "bot" if getattr(chat, "bot", False) else "user"
        elif isinstance(chat, Chat):
            chat_type = "group"
        elif isinstance(chat, Channel):
            chat_type = "supergroup" if getattr(chat, "megagroup", False) else "channel"
        else:
            chat_type = "unknown"
        
        # Insertar/actualizar chat
        insert_or_update_chat(
            db,
            chat_id,
            chat_username,
            chat_title,
            chat_type,
            account_phone,
        )
        
        # Insertar/actualizar remitente
        if sender_id is not None:
            fallback_username = sender_username or (str(sender_id) if sender_id is not None else None)
            insert_or_update_sender(
                db,
                sender_id,
                fallback_username,
                sender_first_name,
                sender_last_name,
                sender_is_bot,
                account_phone,
            )
        
        # Determinar tipo de media y ruta
        media_type = _classify_media_type(message) if message.media else None
        media_file_path = None
        
        # Información de reenvío
        forward_sender_id = None
        if message.forward:
            forward_sender_id = getattr(message.forward, "sender_id", None)
        
        # Información de reply
        reply_to_msg_id = None
        if message.reply_to:
            reply_to_msg_id = message.reply_to.reply_to_msg_id
        
        # Asegurar que los valores son tipos primitivos (no métodos)
        edit_date = None
        if hasattr(message, "edit_date") and message.edit_date:
            edit_date = message.edit_date
        
        views = getattr(message, "views", None)
        if callable(views):
            views = None

        forwards = getattr(message, "forwards", None)
        if callable(forwards):
            forwards = None
        
        created_at = message.date if message.date else None

        # Flags booleanos seguros
        pin_flag = bool(getattr(message, "pinned", False))
        silent_flag = bool(getattr(message, "silent", False))
        post_flag = bool(getattr(message, "post", False))
        
        # Insertar mensaje
        insert_message(db, message.id, chat_id, sender_id,
                      message.text, media_type, media_file_path,
                      bool(message.forward), forward_sender_id, reply_to_msg_id,
                      edit_date,
                      views,
                      forwards,
                      pin_flag,
                      silent_flag,
                      post_flag,
                      getattr(message, "ttl_period", None),
                      getattr(message, "topic_id", None),
                      False,
                      created_at,
                      account_phone)
        gap = message.id - previous_max_id

        # Log de versión (mensaje original)
        insert_message_log(db, message.id, chat_id, sender_id,
                   message.text, media_type, media_file_path,
                   bool(message.forward), reply_to_msg_id,
                   edited=False,
                   edit_date=edit_date,
                   created_at=created_at,
                   account_phone=account_phone)
        
        # Insertar reacciones si existen
        if hasattr(message, "reactions") and message.reactions:
            reactions_data = []
            if hasattr(message.reactions, "results"):
                for reaction in message.reactions.results:
                    emoji_text = reaction.reaction.emoticon if hasattr(reaction.reaction, "emoticon") else str(reaction.reaction)
                    reactions_data.append({
                        "emoji": emoji_text,
                        "count": reaction.count if hasattr(reaction, "count") else 1
                    })
            insert_reactions(db, message.id, chat_id, reactions_data, account_phone)
        
        # Insertar entidades (menciones, hashtags, URLs, etc.)
        if message.entities:
            entities_data = []
            for entity in message.entities:
                entity_type = type(entity).__name__
                offset = entity.offset
                length = entity.length
                # Extraer texto de la entidad
                text = message.text[offset:offset+length] if message.text else None
                entities_data.append({
                    "type": entity_type,
                    "offset": offset,
                    "length": length,
                    "text": text
                })
            insert_entities(db, message.id, chat_id, entities_data, account_phone)
    except Exception as exc:
        logger.error(f"Error guardando mensaje en BD: {exc}")
    finally:
        close_db_connection(db)
    
    # Determinar tipo de contenido (para log)
    content_type = "texto"
    content_preview = message.text or "(vacío)"
    
    if message.media:
        media_type = type(message.media).__name__
        content_type = f"media ({media_type})"
        content_preview = f"[{media_type}]"
    
    if message.poll:
        content_type = "encuesta"
        poll_q = getattr(message.poll, "question", None) or "(sin pregunta)"
        content_preview = f"[Encuesta: {poll_q}]"
    
    if message.contact:
        content_type = "contacto"
        content_preview = f"[Contacto: {message.contact.first_name}]"
    
    # Construir log detallado con ID único y nombre como referencia
    timestamp = message.date.isoformat() if message.date else "N/A"
    msg_id = message.id
    reply_to = f" (respuesta a {message.reply_to.reply_to_msg_id})" if message.reply_to else ""
    is_forward = " [REENVIADO]" if message.forward else ""
    
    log_header = f"[chat_id={chat_id} ({chat_name})] MSG#{msg_id} | {timestamp} | {sender_name}{reply_to}{is_forward}"
    log_content = f"Tipo: {content_type} | {content_preview}"
    
    logger_live.info(log_header)
    logger_live.info(f"  {log_content}")
    
    # Si hay media y está permitido, encolamos para descarga asíncrona y no bloqueante
    # Esto es no-bloqueante: si falla, solo se registra, no afecta al mensaje guardado
    if download and message.media:
        try:
            await _enqueue_media_download(message, chat, media_dir, max_mb, account_phone)
        except Exception as exc:
            logger.warning(f"  ⚠ Error encolando media para msg_id={message.id}: {exc}")
    
    # Detectar gaps y lanzar catch-up automático en background (independiente de si hay media)
    if gap is not None and gap > HISTORIC_GAP_THRESHOLD:
        asyncio.create_task(_catch_up_chat_background(client, chat_id, download, media_dir, max_mb, account_phone))
        logger.info(f"Gap detectado en {chat_id}: {gap} msgs, catch-up en background")

    return None


async def _process_edited_message(client: TelegramClient, message, download: bool, media_dir: Optional[str], max_mb: Optional[int], logger_live=None, account_phone: str = None) -> Optional[str]:
    if logger_live is None:
        logger_live = logger
    if account_phone is None:
        account_phone = os.environ.get("TG_PHONE", "unknown")
    sender = await message.get_sender()
    sender_id = getattr(sender, "id", None)
    sender_username = getattr(sender, "username", None) if sender else None
    sender_first_name = getattr(sender, "first_name", None) if sender else None
    sender_last_name = getattr(sender, "last_name", None) if sender else None
    sender_is_bot = bool(getattr(sender, "bot", False)) if sender else False
    sender_name = (
        sender_username
        or (sender_first_name if sender_first_name else None)
        or (str(sender_id) if sender_id is not None else "desconocido")
    )
    chat = await message.get_chat()
    chat_username = getattr(chat, "username", None)
    chat_title = getattr(chat, "title", None)
    if chat_title is None and isinstance(chat, User):
        name_parts = [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]
        name_combined = " ".join([p for p in name_parts if p]) or None
        chat_title = name_combined or chat_username
    if chat_title is None:
        chat_title = chat_username or str(message.chat_id)
    chat_name = chat_title
    chat_id = message.chat_id

    db = get_db_connection()
    try:
        # Actualizar chat y remitente por si cambian username/title
        if isinstance(chat, User):
            chat_type = "bot" if getattr(chat, "bot", False) else "user"
        elif isinstance(chat, Chat):
            chat_type = "group"
        elif isinstance(chat, Channel):
            chat_type = "supergroup" if getattr(chat, "megagroup", False) else "channel"
        else:
            chat_type = "unknown"
        insert_or_update_chat(
            db,
            chat_id,
            chat_username,
            chat_title,
            chat_type,
            account_phone,
        )
        if sender_id is not None:
            fallback_username = sender_username or (str(sender_id) if sender_id is not None else None)
            insert_or_update_sender(
                db,
                sender_id,
                fallback_username,
                sender_first_name,
                sender_last_name,
                sender_is_bot,
                account_phone,
            )

        media_type = _classify_media_type(message) if message.media else None
        media_file_path = None

        forward_sender_id = None
        if message.forward:
            forward_sender_id = getattr(message.forward, "sender_id", None)

        reply_to_msg_id = None
        if message.reply_to:
            reply_to_msg_id = message.reply_to.reply_to_msg_id

        edit_date = message.edit_date if hasattr(message, "edit_date") else None
        views = getattr(message, "views", None)
        if callable(views):
            views = None
        forwards = getattr(message, "forwards", None)
        if callable(forwards):
            forwards = None

        pin_flag = bool(getattr(message, "pinned", False))
        silent_flag = bool(getattr(message, "silent", False))
        post_flag = bool(getattr(message, "post", False))

        # No sobrescribimos el mensaje original: guardamos una versión nueva marcada como editada
        insert_message_log(db, message.id, chat_id, sender_id,
                           message.text, media_type, media_file_path,
                           bool(message.forward), reply_to_msg_id,
                           edited=True,
                           edit_date=edit_date,
                           created_at=message.date or edit_date,
                           account_phone=account_phone)

        # Refrescar reacciones
        if hasattr(message, "reactions") and message.reactions:
            reactions_data = []
            if hasattr(message.reactions, "results"):
                for reaction in message.reactions.results:
                    emoji_text = reaction.reaction.emoticon if hasattr(reaction.reaction, "emoticon") else str(reaction.reaction)
                    reactions_data.append({
                        "emoji": emoji_text,
                        "count": reaction.count if hasattr(reaction, "count") else 1
                    })
            insert_reactions(db, message.id, chat_id, reactions_data, account_phone)

        # Refrescar entidades
        if message.entities:
            entities_data = []
            for entity in message.entities:
                entity_type = type(entity).__name__
                offset = entity.offset
                length = entity.length
                text = message.text[offset:offset+length] if message.text else None
                entities_data.append({
                    "type": entity_type,
                    "offset": offset,
                    "length": length,
                    "text": text
                })
            insert_entities(db, message.id, chat_id, entities_data, account_phone)
        db.commit()
    except Exception as exc:
        logger.error(f"Error guardando mensaje editado en BD: {exc}")
    finally:
        close_db_connection(db)
    content_type = "texto"
    content_preview = message.text or "(vacío)"
    if message.media:
        media_type = type(message.media).__name__
        content_type = f"media ({media_type})"
        content_preview = f"[{media_type}]"
    if message.poll:
        content_type = "encuesta"
        poll_q = getattr(message.poll, "question", None) or "(sin pregunta)"
        content_preview = f"[Encuesta: {poll_q}]"
    if message.contact:
        content_type = "contacto"
        content_preview = f"[Contacto: {message.contact.first_name}]"

    timestamp = message.edit_date.isoformat() if message.edit_date else (message.date.isoformat() if message.date else "N/A")
    reply_to = f" (respuesta a {message.reply_to.reply_to_msg_id})" if message.reply_to else ""
    is_forward = " [REENVIADO]" if message.forward else ""
    log_header = f"[chat_id={chat_id} ({chat_name})] MSG#{message.id} (EDITADO) | {timestamp} | {sender_name}{reply_to}{is_forward}"
    log_content = f"Tipo: {content_type} | {content_preview}"
    logger_live.info(log_header)
    logger_live.info(f"  {log_content}")

    # Si hay media y está permitido, encolamos para descarga (no bloqueante)
    # Cualquier error al encolar no afecta el guardado del mensaje editado
    if download and message.media:
        try:
            await _enqueue_media_download(message, chat, media_dir, max_mb, account_phone)
        except Exception as exc:
            logger.warning(f"  ⚠ Error encolando media editada para msg_id={message.id}: {exc}")

    return None


async def resolve_chat(client: TelegramClient, ref: str):
    try:
        return await client.get_entity(ref)
    except Exception:
        # Fallback: buscar por nombre en diálogos (útil para grupos normales por ID)
        try:
            async for dialog in client.iter_dialogs(limit=1000):
                if str(dialog.id) == ref or dialog.name == ref:
                    return dialog.entity
        except Exception:
            pass
        raise RuntimeError(f"No se pudo resolver el chat '{ref}'")


async def send_message(client: TelegramClient, target: str, text: str) -> None:
    entity = await resolve_chat(client, target)
    await client.send_message(entity, text)
    logger.info("Mensaje enviado")


async def show_history(client: TelegramClient, target: str, limit: int) -> None:
    entity = await resolve_chat(client, target)
    logger.info("Últimos mensajes:")
    async for message in client.iter_messages(entity, limit=limit):
        author = message.sender_id
        print(f"[{message.id}] {author}: {message.text}")


async def catch_up_chat(client: TelegramClient, target: str, download: bool = False, media_dir: Optional[str] = None, max_mb: Optional[int] = None, account_phone: str = None) -> None:
    """Descarga todos los mensajes faltantes de un chat (basado en BD, no en state.json)."""
    entity = await resolve_chat(client, target)
    chat_id = (await client.get_entity(entity)).id
    
    # Obtener el ID más alto de mensaje guardado en la BD para este chat
    db = get_db_connection()
    try:
        max_msg_id_in_db = get_max_message_id_in_chat(db, chat_id, account_phone)
    finally:
        close_db_connection(db)
    
    logger.info(f"Catch-up para chat {chat_id}: buscando mensajes con ID > {max_msg_id_in_db}")
    
    # Semáforo más conservador para evitar saturación cuando hay múltiples listeners
    # Con 64 clientes: 64 × 25 = 1,600 tareas máximo
    semaphore = asyncio.Semaphore(25)
    
    async def process_with_limit(msg):
        async with semaphore:
            max_retries = 5
            retry_count = 0
            last_exception = None
            
            while retry_count < max_retries:
                try:
                    await _process_message(client, msg, download, media_dir, max_mb, logger_catchup, account_phone)
                    return  # Éxito
                except Exception as e:
                    retry_count += 1
                    last_exception = e
                    if retry_count < max_retries:
                        wait_time = 2 ** retry_count  # Backoff exponencial: 2s, 4s, 8s, 16s, 32s
                        logger.warning(f"Error en MSG#{msg.id} (intento {retry_count}/{max_retries}), reintentando en {wait_time}s: {str(e)}")
                        await asyncio.sleep(wait_time + 0.5)  # +0.5s para liberar pool
                    else:
                        logger.exception(f"❌ FALLO CRÍTICO: MSG#{msg.id} en chat {chat_id} tras {max_retries} reintentos. NO SE GUARDÓ EL MENSAJE.")
                        logger.exception(f"Última excepción: {last_exception}")
    
    # Procesar mensajes en batches grandes para máximo rendimiento
    count_catchup = 0
    batch_size = 200
    tasks = []
    
    async for msg in client.iter_messages(entity, min_id=max_msg_id_in_db, limit=None, reverse=True, wait_time=0.5):
        tasks.append(asyncio.create_task(process_with_limit(msg)))
        count_catchup += 1
        
        # Procesar batch cuando alcance el límite
        if len(tasks) >= batch_size:
            await asyncio.gather(*tasks)
            tasks = []
            if count_catchup % 250 == 0:
                logger.info(f"Catch-up: {count_catchup} mensajes procesados...")
    
    # Procesar mensajes restantes
    if tasks:
        await asyncio.gather(*tasks)
    
    logger.info(f"✓ Catch-up completado: {count_catchup} mensajes procesados en chat {chat_id}")


async def run_listener(client: TelegramClient, target: Optional[str], download: bool = False, media_dir: Optional[str] = None, catch_up: bool = False, max_mb: Optional[int] = None) -> None:
    # Obtener account_phone del entorno
    account_phone = os.environ.get("TG_PHONE", "unknown")
    
    chats = None
    if target:
        entity = await resolve_chat(client, target)
        chats = entity
        logger.info("Escuchando solo el chat indicado")
    else:
        logger.info("Escuchando todos los chats. Ctrl+C para salir.")

    # Estado de último mensaje
    state = _load_state()

    # Registrar event handlers para mensajes en tiempo real ANTES del catch-up
    # Esto permite recibir mensajes live mientras se procesa el catch-up en paralelo
    logger.info("="*80)
    logger.info("🟢 Registrando event handlers para NewMessage y MessageEdited...")
    
    @client.on(events.NewMessage(chats=chats))
    async def handler(event):
        max_retries = 5
        retry_count = 0
        last_exception = None
        
        while retry_count < max_retries:
            try:
                await _process_message(client, event.message, download, media_dir, max_mb, logger_live, account_phone)
                return  # Éxito
            except Exception as e:
                retry_count += 1
                last_exception = e
                if retry_count < max_retries:
                    wait_time = 2 ** retry_count
                    logger.warning(f"Error en MSG#{event.message.id} (intento {retry_count}/{max_retries}), reintentando en {wait_time}s: {str(e)}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.exception(f"❌ FALLO CRÍTICO: MSG#{event.message.id} en chat {event.chat_id} tras {max_retries} reintentos. NO SE GUARDÓ.")
                    logger.exception(f"Última excepción: {last_exception}")
        _update_last_id(state, event.chat_id, event.message.id)
        _save_state(state)

    @client.on(events.MessageEdited(chats=chats))
    async def edited_handler(event):
        max_retries = 5
        retry_count = 0
        last_exception = None
        
        while retry_count < max_retries:
            try:
                await _process_edited_message(client, event.message, download, media_dir, max_mb)
                return  # Éxito
            except Exception as e:
                retry_count += 1
                last_exception = e
                if retry_count < max_retries:
                    wait_time = 2 ** retry_count
                    logger.warning(f"Error en EDIT MSG#{event.message.id} (intento {retry_count}/{max_retries}), reintentando en {wait_time}s: {str(e)}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.exception(f"❌ FALLO CRÍTICO: EDIT MSG#{event.message.id} en chat {event.chat_id} tras {max_retries} reintentos. NO SE ACTUALIZÓ.")
                    logger.exception(f"Última excepción: {last_exception}")
        _update_last_id(state, event.chat_id, event.message.id)
        _save_state(state)

    logger.info("🟢 Event handlers registrados correctamente")
    logger.info("🟢 ✓ Listener activo para mensajes en tiempo real")
    logger.info("="*80 + "\n")

    # Iniciar procesamiento de descargas en background (paralelo con todo)
    download_task = None
    if download:
        logger.info("="*80)
        logger.info("📥 INICIANDO PROCESADOR DE DESCARGAS EN BACKGROUND")
        logger.info("="*80)
        download_task = asyncio.create_task(
            process_download_queue(client, media_dir, max_mb, concurrency=8, stop_when_empty=False)
        )
        logger.info("🟢 ✓ Procesador de descargas activo en paralelo")
        logger.info("="*80 + "\n")

    # Catch-up opcional (basado en BD, no en state.json)
    # Se ejecuta en paralelo con los event handlers y las descargas
    if catch_up:
        try:
            if chats is not None:
                # Catch-up para un chat específico
                chat_id = (await client.get_entity(chats)).id if not isinstance(chats, int) else chats
                key = str(chat_id)
                
                db = get_db_connection()
                try:
                    max_msg_id_in_db = get_max_message_id_in_chat(db, chat_id, account_phone)
                finally:
                    close_db_connection(db)
                
                logger.info(f"Catch-up para chat {key}: buscando mensajes con ID > {max_msg_id_in_db}")
                
                # Semáforo balanceado para velocidad sin saturar pool ni flood wait de Telegram
                # Con 64 clientes: 64 × 50 = 3,200 tareas (< pool 250 × 64 = 16,000)
                semaphore = asyncio.Semaphore(50)
                
                async def process_with_limit(msg):
                    async with semaphore:
                        max_retries = 5
                        retry_count = 0
                        last_exception = None
                        
                        while retry_count < max_retries:
                            try:
                                await _process_message(client, msg, download, media_dir, max_mb, logger_catchup, account_phone)
                                return  # Éxito
                            except Exception as e:
                                retry_count += 1
                                last_exception = e
                                if retry_count < max_retries:
                                    wait_time = 2 ** retry_count  # Backoff exponencial: 2s, 4s, 8s, 16s, 32s
                                    logger.warning(f"Error en MSG#{msg.id} (intento {retry_count}/{max_retries}), reintentando en {wait_time}s: {str(e)}")
                                    await asyncio.sleep(wait_time + 0.1)  # +0.1s para liberar pool
                                else:
                                    logger.exception(f"❌ FALLO CRÍTICO: MSG#{msg.id} en chat {chat_id} tras {max_retries} reintentos. NO SE GUARDÓ EL MENSAJE.")
                                    logger.exception(f"Última excepción: {last_exception}")
                
                count_catchup = 0
                batch_size = 200
                tasks = []
                
                async for msg in client.iter_messages(chats, min_id=max_msg_id_in_db, reverse=True):
                    tasks.append(asyncio.create_task(process_with_limit(msg)))
                    _update_last_id(state, msg.chat_id, msg.id)
                    count_catchup += 1
                    
                    # Procesar batch cuando alcance el límite
                    if len(tasks) >= batch_size:
                        await asyncio.gather(*tasks)
                        tasks = []
                
                # Procesar mensajes restantes
                if tasks:
                    await asyncio.gather(*tasks)
                
                _save_state(state)
                logger.info(f"Catch-up completado: {count_catchup} mensajes procesados")
            else:
                # Catch-up para TODOS los chats
                logger.info("Catch-up para TODOS los chats (iterativo hasta completar TODOS los gaps)...")
                
                # Semáforo balanceado para velocidad sin saturar pool ni flood wait de Telegram
                # Con 64 clientes: 64 × 50 = 3,200 tareas (< pool 250 × 64 = 16,000)
                semaphore = asyncio.Semaphore(50)
                
                global_iteration = 0
                total_global_catchup = 0
                
                async def process_with_limit(msg, chat_id, dialog_name):
                    async with semaphore:
                        max_retries = 5
                        retry_count = 0
                        last_exception = None
                        
                        while retry_count < max_retries:
                            try:
                                await _process_message(client, msg, download, media_dir, max_mb, logger_catchup, account_phone)
                                return  # Éxito
                            except Exception as e:
                                retry_count += 1
                                last_exception = e
                                if retry_count < max_retries:
                                    wait_time = 2 ** retry_count  # Backoff exponencial: 2s, 4s, 8s, 16s, 32s
                                    logger.warning(f"Error en MSG#{msg.id} en {dialog_name} (intento {retry_count}/{max_retries}), reintentando en {wait_time}s: {str(e)}")
                                    await asyncio.sleep(wait_time)
                                else:
                                    logger.exception(f"❌ FALLO CRÍTICO: MSG#{msg.id} en chat {chat_id} ({dialog_name}) tras {max_retries} reintentos. NO SE GUARDÓ.")
                                    logger.exception(f"Última excepción: {last_exception}")
                
                while True:
                    global_iteration += 1
                    logger.info(f"\n=== PASADA {global_iteration} de catch-up global ===")

                    # Si el cliente se cayó, reconectar antes de intentar iterar diálogos.
                    if not await _ensure_connected(client, sleep_seconds=10):
                        continue
                    
                    total_catchup = 0
                    total_gaps_filled = 0
                    total_dialogs = 0
                    async for dialog in iter_all_dialogs(client):
                        total_dialogs += 1
                        chat_id = dialog.id
                        db = get_db_connection()
                        try:
                            max_msg_id_in_db = get_max_message_id_in_chat(db, chat_id, account_phone)
                            # Obtener gaps intermedios
                            gaps = get_chat_gaps(db, chat_id, account_phone, limit=100)  # Top 100 gaps más grandes
                        finally:
                            close_db_connection(db)
                        
                        logger.info(f"  [{total_dialogs}] → Chat '{dialog.name}' (id={chat_id})")
                        count_catchup = 0
                        tasks = []
                        batch_size = 200
                        
                        try:
                            # PASO 1: Obtener mensajes NUEVOS (posteriores al último guardado)
                            logger.info(f"      Buscando mensajes nuevos desde id>{max_msg_id_in_db}")
                            async for msg in client.iter_messages(dialog.entity, min_id=max_msg_id_in_db, limit=None, reverse=True, wait_time=0.5):
                                tasks.append(asyncio.create_task(process_with_limit(msg, chat_id, dialog.name)))
                                _update_last_id(state, msg.chat_id, msg.id)
                                count_catchup += 1
                                
                                # Procesar batch cuando alcance el límite
                                if len(tasks) >= batch_size:
                                    await asyncio.gather(*tasks)
                                    tasks = []
                                    if count_catchup % 250 == 0:
                                        logger.info(f"      Procesados {count_catchup} mensajes nuevos...")
                            
                            # Procesar mensajes restantes
                            if tasks:
                                await asyncio.gather(*tasks)
                            
                            # PASO 2: Rellenar GAPS intermedios
                            if gaps:
                                logger.info(f"      🔍 Encontrados {len(gaps)} gaps - Rellenando los más grandes...")
                                gaps_filled = 0
                                for gap_row in gaps[:10]:  # Procesar top 10 gaps más grandes
                                    gap_start = int(gap_row['gap_start']) if isinstance(gap_row, dict) else int(gap_row[0])
                                    gap_end = int(gap_row['gap_end']) if isinstance(gap_row, dict) else int(gap_row[1])
                                    gap_size = int(gap_row['gap_size']) if isinstance(gap_row, dict) else int(gap_row[2])
                                    
                                    if gap_size > 0:  # Todos los gaps, incluso de 1 mensaje
                                        seen_ids = set()
                                        logger.info(f"      → Rellenando gap: mensajes {gap_start} a {gap_end} ({gap_size} faltantes)")
                                        # Obtener mensajes en el rango del gap
                                        async for msg in client.iter_messages(dialog.entity, 
                                                                             min_id=gap_start-1, 
                                                                             max_id=gap_end+1, 
                                                                             limit=gap_size,
                                                                             reverse=True,
                                                                             wait_time=0.5):
                                            tasks.append(asyncio.create_task(process_with_limit(msg, chat_id, dialog.name)))
                                            count_catchup += 1
                                            gaps_filled += 1
                                            seen_ids.add(msg.id)
                                            
                                            if len(tasks) >= batch_size:
                                                await asyncio.gather(*tasks)
                                                tasks = []
                                        
                                        # Procesar batch del gap
                                        if tasks:
                                            await asyncio.gather(*tasks)
                                            tasks = []

                                        # Marcar como irrecuperables los ids no devueltos por Telegram
                                        missing_ids = set(range(gap_start, gap_end + 1)) - seen_ids
                                        if missing_ids:
                                            db_placeholder = get_db_connection()
                                            try:
                                                for missing_id in sorted(missing_ids):
                                                    mark_message_unrecoverable(db_placeholder, chat_id, missing_id, account_phone, "telegram_missing")
                                                db_placeholder.commit()
                                            finally:
                                                close_db_connection(db_placeholder)
                                
                                if gaps_filled > 0:
                                    logger.info(f"      ✓ Rellenados {gaps_filled} mensajes en gaps")
                                    total_gaps_filled += gaps_filled
                            
                            if count_catchup == 0:
                                logger.info(f"      ⊘ Sin mensajes nuevos ni gaps")
                            else:
                                logger.info(f"      ✓ Total procesado: {count_catchup} mensajes")
                            total_catchup += count_catchup
                        except Exception as e:
                            logger.warning(f"    ✗ Error en catch-up de '{dialog.name}': {e}")
                    
                    _save_state(state)
                    logger.info(f"✓ Pasada {global_iteration}: {total_dialogs} chats, {total_catchup} mensajes ({total_gaps_filled} gaps rellenados)")
                    total_global_catchup += total_catchup
                    
                    # Si no hay nuevos mensajes ni gaps, dormir y seguir sondeando
                    if total_catchup == 0:
                        logger.info(f"✓ Convergencia alcanzada en pasada {global_iteration} - no hay nuevos mensajes ni gaps")
                        await asyncio.sleep(3)
                        continue
                    
                    # Aún hay mensajes: continuar siguiente pasada inmediatamente
                    logger.info(f"⏳ Aún hay mensajes pendientes - Iniciando pasada {global_iteration + 1}...")
                
                logger.info(f"\n✓ Catch-up iterativo completado: {total_global_catchup} mensajes totales en {global_iteration} pasada(s)")
                logger.info("🟢 Catch-up finalizado - Procesador de descargas continúa en background")
                logger.info(f"\n✓ Catch-up iterativo completado: {total_global_catchup} mensajes totales en {global_iteration} pasada(s)")
                
                # Procesar cola de descargas después del catch-up
                if download:
                    logger.info("\n" + "="*80)
                    logger.info("📥 PROCESANDO COLA DE DESCARGAS PENDIENTES")
                    logger.info("="*80)
                    await process_download_queue(client, media_dir, max_mb, concurrency=8, stop_when_empty=True)
        except Exception as exc:
            logger.error(f"Error en catch-up: {exc}")
    
    # Mantener el cliente activo para recibir eventos en tiempo real
    # El catch-up (si estaba activo) ya terminó, ahora solo escuchamos eventos nuevos
    logger.info("\n" + "="*80)
    logger.info("🟢 ✓ Listener activo - Esperando eventos en tiempo real...")
    logger.info("="*80 + "\n")
    
    await client.run_until_disconnected()


# ============================================================================
# ARQUITECTURA ANTIGUA (DEPRECATED - MANTENER POR REFERENCIAS HISTÓRICAS)
# Estas funciones se mantienen solo por documentación del cambio de arquitectura
# De: Polling multi-thread (3 threads) a Event-driven (1 async loop)
# ============================================================================
# - run_live_listener_thread() - REEMPLAZADO por run_listener_with_events()
# - run_catchup_worker_thread() - Funcionalidad integrada en FileSession recovery
# - run_download_worker_thread() - NO SE USA EN ARQUITECTURA SIMPLIFICADA
# - thread_wrapper() - NO SE USA (asyncio.run() directo)
# ============================================================================


async def run_listener_with_events(target: Optional[str] = None):
    """
    Ejecuta listener único con event handlers en tiempo real (sin polling).
    FileSession + event handlers = captura real-time eficiente de mensajes nuevos.
    Diferencia entre LIVE (tiempo real) y CATCHUP (históricos del FileSession).
    """
    logger.info("="*80)
    logger.info("🚀 INICIANDO LISTENER CON EVENT HANDLERS")
    logger.info("="*80)
    
    client = build_client()
    
    async with client:
        logger.info("🟢 Cliente conectado")
        
        # Verificar conexión
        try:
            me = await client.get_me()
            logger.info(f"🟢 Verificación OK: {me.username or me.first_name}")
        except Exception as e:
            logger.error(f"❌ Error verificando conexión: {e}")
            return
        
        # Timestamp de referencia: mensajes más antiguos que esto son CATCHUP
        import time
        connection_time = time.time()
        catchup_threshold = 30  # segundos - mensajes más antiguos son catch-up histórico
        
        # Obtener chats a monitorear
        chats_to_monitor = None
        if target:
            try:
                entity = await resolve_chat(client, target)
                chats_to_monitor = [entity]
                logger.info(f"🟢 Monitoreando chat específico: {entity}")
            except Exception as e:
                logger.error(f"Error resolviendo chat {target}: {e}")
                return
        
        # Registrar event handler para mensajes nuevos
        @client.on(events.NewMessage())
        async def handle_new_message(event):
            try:
                message = event.message
                chat_id = message.chat_id
                
                # Filtro: solo si estamos monitoreando este chat (si target especificado)
                if target and chats_to_monitor:
                    chat_matches = any(
                        chat_id == (c.id if hasattr(c, 'id') else c)
                        for c in chats_to_monitor
                    )
                    if not chat_matches:
                        return
                
                # Diferenciar CATCHUP (históricos) de LIVE (tiempo real)
                try:
                    msg_timestamp = message.date.timestamp()
                except (AttributeError, TypeError):
                    msg_timestamp = message.date
                
                time_since_msg = time.time() - msg_timestamp
                
                # Determinar tipo de mensaje y logger a usar
                if time_since_msg > catchup_threshold:
                    msg_type = "CATCHUP"
                    msg_logger = logger_catchup  # Log a tel-cli.catchup.log
                else:
                    msg_type = "LIVE"
                    msg_logger = logger_live  # Log a tel-cli.live.log
                
                msg_logger.info(f"🟢 [{msg_type}] ✉️ NUEVO MENSAJE: Chat={chat_id}, ID={message.id}, User={message.sender_id}")
                
                # Procesar el mensaje (usa el mismo logger para el detalle)
                await _process_message(client, message, False, None, None, msg_logger)
                
            except Exception as e:
                logger.exception(f"Error procesando evento de mensaje: {e}")
        
        logger.info("🟢 Event handler registrado para NewMessage")
        logger.info("🟢 ✓ Listener activo - Esperando eventos en tiempo real...")
        logger.info("="*80 + "\n")
        
        # Mantener el cliente escuchando
        await client.run_until_disconnected()


async def run_multithreaded_listener(target: Optional[str] = None, download: bool = False, 
                               media_dir: Optional[str] = None, max_mb: Optional[int] = None, catch_up: bool = False):
    """
    Ejecuta listener con event handlers, soporte para catch-up y descargas.
    Integra toda la lógica en un único event loop asincrónico.
    """
    logger.info("="*80)
    logger.info("🚀 INICIANDO LISTENER DE MENSAJES EN TIEMPO REAL")
    logger.info("="*80)
    
    # Construir cliente y verificar autorización SIN start() (start() intenta login interactivo).
    # En contenedor, si la sesión no es válida, eso provoca EOF y reinicios en bucle.
    phone = os.environ.get("TG_PHONE")

    while True:
        client = build_client()
        try:
            await client.connect()
            if await client.is_user_authorized():
                break

            logger.error(
                "❌ Sesión no autorizada para este cliente. "
                "Ejecuta 'docker compose run --rm telegram-init' para autenticar y regenerar la sesión. "
                "Reintentando en 30s..."
            )
        finally:
            await client.disconnect()

        await asyncio.sleep(30)

    # Sesión OK: ya podemos ejecutar listener (y mantener conectado).
    async with client:
        await ensure_login(client, phone)
        await run_listener(client, target, download=download, media_dir=media_dir, catch_up=catch_up, max_mb=max_mb)


async def dispatch(args) -> None:
    phone = os.environ.get("TG_PHONE")
    
    # El comando listen usa event handlers en un solo loop
    if args.command == "listen":
        await run_multithreaded_listener(
            target=args.chat,
            download=args.download,
            media_dir=args.media_dir,
            max_mb=args.max_mb,
            catch_up=args.catch_up
        )
        return
    
    # Resto de comandos usan el cliente normalmente
    client = build_client()

    async with client:
        if args.command == "init":
            # Comando de inicialización: autenticación interactiva
            await ensure_login(client, phone)
            me = await client.get_me()
            logger.info(f"✓ Autenticado como: {me.first_name} (@{me.username}) - ID: {me.id}")
            
            # Si se solicita, exportar StringSession
            if args.export_string:
                session_string = StringSession.save(client.session)
                print("\n" + "="*80)
                print("✅ SESIÓN AUTENTICADA CORRECTAMENTE")
                print("="*80)
                print("\n📋 Guarda esta línea en tu archivo .env o secreto de Docker:\n")
                print(f"TG_SESSION_STRING={session_string}")
                print("\n" + "="*80)
                print("💡 Con esta variable, no necesitas archivos .session")
                print("   Úsala en docker-compose.yml o en variables de entorno del contenedor")
                print("="*80 + "\n")
            else:
                print(f"\n✓ Sesión guardada en archivo: {args.session or os.environ.get('TG_SESSION', 'me')}.session")
                print("  Puedes copiar este archivo al contenedor o usar --export-string para obtener un string\n")
            return
        
        await ensure_login(client, phone)

        if args.command == "list":
            await list_dialogs(client, args.limit)
        elif args.command == "send":
            await send_message(client, args.to, args.text)
        elif args.command == "history":
            await show_history(client, args.chat, args.limit)
        elif args.command == "catch-up":
            await catch_up_chat(client, args.chat, download=args.download, media_dir=args.media_dir, max_mb=args.max_mb, account_phone=phone)
            # Procesar cola hasta vaciarla para esta ejecución
            await process_download_queue(client, args.media_dir, args.max_mb, concurrency=8, stop_when_empty=True)
        elif args.command == "history-since":
            entity = await resolve_chat(client, args.chat)
            state = _load_state()
            key = str((await client.get_entity(entity)).id)
            min_id = args.min_id if args.min_id is not None else state.get(key, {}).get("last_id", 0)
            logger.info(f"Mostrando mensajes desde id>{min_id}")
            async for msg in client.iter_messages(entity, min_id=min_id, limit=args.limit, reverse=True):
                author = msg.sender_id
                print(f"[{msg.id}] {author}: {msg.text}")
        elif args.command == "db-stats":
            db = get_db_connection()
            try:
                from .db import get_stats
                stats = get_stats(db)
                print("\n=== Estadísticas de BD ===")
                for key, value in stats.items():
                    print(f"{key}: {value}")
            finally:
                close_db_connection(db)
        elif args.command == "db-export":
            db = get_db_connection()
            try:
                from .db import export_messages_json
                count = export_messages_json(db, args.output or "messages_export.json")
                print(f"✓ Exportados {count} mensajes a {args.output or 'messages_export.json'}")
            finally:
                close_db_connection(db)
        elif args.command == "db-chat":
            db = get_db_connection()
            try:
                from .db import get_messages_by_chat
                if args.chat_id < 0:
                    # Es un chat ID real
                    chat_id = args.chat_id
                else:
                    # Resolver el nombre/username a ID
                    entity = await resolve_chat(client, str(args.chat_id))
                    chat_id = (await client.get_entity(entity)).id
                
                messages = get_messages_by_chat(db, chat_id, limit=args.limit)
                print(f"\n=== Últimos {len(messages)} mensajes del chat {chat_id} ===")
                for msg in messages:
                    print(f"[{msg['msg_id']}] {msg['sender_id']}: {msg['text'][:100] if msg['text'] else '(sin texto)'}")
            finally:
                close_db_connection(db)
        else:
            raise RuntimeError("Comando no reconocido")


def parse_args():
    parser = argparse.ArgumentParser(description="Cliente personal de Telegram con Telethon")
    parser.add_argument("--session", help="Nombre de sesión (por defecto TG_SESSION o 'me'). Útil para múltiples instancias simultáneas.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Inicialización interactiva: autenticación y generación de StringSession")
    p_init.add_argument("--export-string", action="store_true", help="Exportar StringSession al finalizar")

    p_list = sub.add_parser("list", help="Listar diálogos")
    p_list.add_argument("--limit", type=int, default=20, help="Número máximo de diálogos")

    p_send = sub.add_parser("send", help="Enviar mensaje")
    p_send.add_argument("--to", required=True, help="chat_id o @username")
    p_send.add_argument("--text", required=True, help="Contenido del mensaje")

    p_hist = sub.add_parser("history", help="Ver historial de un chat")
    p_hist.add_argument("--chat", required=True, help="chat_id o @username")
    p_hist.add_argument("--limit", type=int, default=20, help="Mensajes a mostrar")

    p_catchup = sub.add_parser("catch-up", help="Descargar todos los mensajes faltantes de un chat (no en BD)")
    p_catchup.add_argument("--chat", required=True, help="chat_id o @username")
    p_catchup.add_argument("--download", action="store_true", help="Descargar media de los mensajes")
    p_catchup.add_argument("--media-dir", help="Carpeta base para guardar media (por defecto TG_MEDIA_DIR o 'downloads')")
    p_catchup.add_argument("--max-mb", type=int, default=None, help="No descargar ficheros mayores a este tamaño en MB (sin límite por defecto)")

    p_listen = sub.add_parser("listen", help="Escuchar nuevos mensajes")
    p_listen.add_argument("--chat", help="chat_id o @username; si se omite, escucha todos")
    p_listen.add_argument("--download", action="store_true", help="Descargar media de nuevos mensajes")
    p_listen.add_argument("--media-dir", help="Carpeta base para guardar media (por defecto TG_MEDIA_DIR o 'downloads')")
    p_listen.add_argument("--catch-up", action="store_true", help="Procesar mensajes pendientes (sin --chat: todos los chats)")
    p_listen.add_argument("--max-mb", type=int, default=None, help="No descargar ficheros mayores a este tamaño en MB (sin límite por defecto)")

    p_since = sub.add_parser("history-since", help="Ver historial a partir de un id mínimo")
    p_since.add_argument("--chat", required=True, help="chat_id o @username")
    p_since.add_argument("--min-id", type=int, help="Id mínimo (si no, usa el último guardado en estado)")
    p_since.add_argument("--limit", type=int, default=50, help="Mensajes a mostrar")

    p_db_stats = sub.add_parser("db-stats", help="Ver estadísticas de la BD")

    p_db_export = sub.add_parser("db-export", help="Exportar todos los mensajes a JSON")
    p_db_export.add_argument("--output", help="Archivo de salida (por defecto: messages_export.json)")

    p_db_chat = sub.add_parser("db-chat", help="Ver mensajes de un chat desde la BD")
    p_db_chat.add_argument("--chat-id", type=int, required=True, help="chat_id o nombre del chat")
    p_db_chat.add_argument("--limit", type=int, default=50, help="Mensajes a mostrar")

    return parser.parse_args()


def main():
    args = parse_args()
    try:
        asyncio.run(dispatch(args))
    except KeyboardInterrupt:
        logger.info("Saliendo...")
    except Exception as exc:  # pragma: no cover - CLI guard
        logger.error(exc)


if __name__ == "__main__":
    main()
