-- Schema de BD para PostgreSQL
-- Este script se ejecuta automáticamente al iniciar el contenedor de PostgreSQL

-- Chats por cuenta
CREATE TABLE IF NOT EXISTS chats (
    chat_id BIGINT NOT NULL,
    account_phone TEXT NOT NULL,
    username TEXT,
    title TEXT,
    chat_type TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, account_phone)
);

-- Remitentes por cuenta
CREATE TABLE IF NOT EXISTS senders (
    user_id BIGINT NOT NULL,
    account_phone TEXT NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    is_bot BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, account_phone)
);

-- Mensajes por chat y cuenta
CREATE TABLE IF NOT EXISTS messages (
    msg_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    account_phone TEXT NOT NULL,
    sender_id BIGINT,
    text TEXT,
    media_type TEXT,
    media_file_path TEXT,
    is_forward BOOLEAN DEFAULT FALSE,
    forward_sender_id BIGINT,
    reply_to_msg_id BIGINT,
    edit_date TIMESTAMP,
    views INTEGER,
    forwards INTEGER,
    pin BOOLEAN DEFAULT FALSE,
    silent BOOLEAN DEFAULT FALSE,
    is_post BOOLEAN DEFAULT FALSE,
    ttl_period INTEGER,
    topic_id BIGINT,
    has_log BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, msg_id, account_phone),
    FOREIGN KEY (chat_id, account_phone) REFERENCES chats (chat_id, account_phone) ON DELETE CASCADE
);

-- Reacciones por mensaje y cuenta
CREATE TABLE IF NOT EXISTS reactions (
    id SERIAL PRIMARY KEY,
    msg_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    account_phone TEXT NOT NULL,
    emoji TEXT,
    count INTEGER,
    FOREIGN KEY (chat_id, msg_id, account_phone) REFERENCES messages (chat_id, msg_id, account_phone) ON DELETE CASCADE
);

-- Entidades por mensaje y cuenta
CREATE TABLE IF NOT EXISTS entities (
    id SERIAL PRIMARY KEY,
    msg_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    account_phone TEXT NOT NULL,
    entity_type TEXT,
    entity_offset INTEGER,
    entity_length INTEGER,
    text TEXT,
    FOREIGN KEY (chat_id, msg_id, account_phone) REFERENCES messages (chat_id, msg_id, account_phone) ON DELETE CASCADE
);

-- Log histórico por mensaje y cuenta
CREATE TABLE IF NOT EXISTS message_log (
    id SERIAL PRIMARY KEY,
    telegram_msg_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    account_phone TEXT NOT NULL,
    sender_id BIGINT,
    text TEXT,
    media_type TEXT,
    media_file_path TEXT,
    is_forward BOOLEAN DEFAULT FALSE,
    reply_to_msg_id BIGINT,
    edited BOOLEAN DEFAULT FALSE,
    edit_date TIMESTAMP,
    created_at TIMESTAMP,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id, telegram_msg_id, account_phone) REFERENCES messages (chat_id, msg_id, account_phone) ON DELETE CASCADE
);

-- Cola de descargas por mensaje y cuenta
CREATE TABLE IF NOT EXISTS download_queue (
    id SERIAL PRIMARY KEY,
    msg_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    chat_label TEXT,
    media_dir TEXT,
    file_size BIGINT,
    file_unique_id TEXT,
    account_phone TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    path TEXT,
    error TEXT,
    attempts INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (chat_id, msg_id, account_phone)
);

-- Preferencias por chat y cuenta
CREATE TABLE IF NOT EXISTS chat_preferences (
    chat_id BIGINT NOT NULL,
    account_phone TEXT NOT NULL,
    media_download_enabled BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (chat_id, account_phone)
);

-- Índices para mejorar rendimiento
CREATE INDEX IF NOT EXISTS idx_message_log_msg ON message_log(telegram_msg_id, account_phone);
CREATE INDEX IF NOT EXISTS idx_message_log_chat ON message_log(chat_id, account_phone);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, account_phone);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id, account_phone);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_received ON messages(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_download_queue_status ON download_queue(status, account_phone);
CREATE INDEX IF NOT EXISTS idx_download_queue_chat ON download_queue(chat_id, account_phone);
CREATE INDEX IF NOT EXISTS idx_download_queue_file_unique ON download_queue(file_unique_id);
CREATE INDEX IF NOT EXISTS idx_reactions_msg ON reactions(msg_id, chat_id, account_phone);
CREATE INDEX IF NOT EXISTS idx_entities_msg ON entities(msg_id, chat_id, account_phone);
