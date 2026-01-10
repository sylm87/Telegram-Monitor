import os
import time
import json
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Optional


def _parse_destinations(value: Optional[str]) -> list[str]:
    if not value:
        return []
    parts = []
    for raw in value.replace(";", ",").replace("\n", ",").split(","):
        item = raw.strip()
        if item:
            parts.append(item)
    return parts


def _chunk_text(text: str, chunk_size: int = 3800) -> list[str]:
    if not text:
        return [""]
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        start = end
    return chunks


def _build_notification_prefix() -> str:
    """Combina TG_NOTIFY_PREFIX con TG_PHONE.

    Ejemplo:
      TG_NOTIFY_PREFIX='[Telegram-Monitor][DEV]'
      TG_PHONE='+34666666666'
      => '[Telegram-Monitor][DEV][+34666666666]'
    """
    raw_prefix = (os.environ.get("TG_NOTIFY_PREFIX") or "").strip()
    raw_phone = (os.environ.get("TG_PHONE") or "").strip()

    pieces: list[str] = []
    if raw_prefix:
        pieces.append(raw_prefix)
    if raw_phone:
        if raw_phone.startswith("[") and raw_phone.endswith("]"):
            pieces.append(raw_phone)
        else:
            pieces.append(f"[{raw_phone}]")
    return "".join(pieces)


@dataclass(frozen=True)
class TelegramNotifyConfig:
    token: str
    chat_ids: tuple[str, ...]
    api_base: str = "https://api.telegram.org"
    timeout_seconds: int = 10


class TelegramBotNotifier:
    def __init__(self, config: Optional[TelegramNotifyConfig], logger=None):
        self._config = config
        self._logger = logger
        self._lock = threading.Lock()
        self._last_sent_by_key: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._config and self._config.token and self._config.chat_ids)

    @classmethod
    def from_env(cls, logger=None) -> "TelegramBotNotifier":
        token = (os.environ.get("TG_NOTIFY_BOT_TOKEN") or "").strip()
        destinations = _parse_destinations(os.environ.get("TG_NOTIFY_CHAT_IDS"))

        if not token or not destinations:
            return cls(None, logger=logger)

        api_base = (os.environ.get("TG_NOTIFY_API_BASE") or "https://api.telegram.org").strip()
        timeout_seconds = int(os.environ.get("TG_NOTIFY_TIMEOUT_SECONDS", "10"))
        cfg = TelegramNotifyConfig(token=token, chat_ids=tuple(destinations), api_base=api_base, timeout_seconds=timeout_seconds)
        return cls(cfg, logger=logger)

    def notify(self, *, key: str, text: str, min_interval_seconds: int = 600) -> bool:
        """Send a notification if rate-limit allows it.

        Returns True if a send was attempted (rate-limit passed), False if skipped.
        """
        if not self.enabled:
            return False

        config = self._config
        assert config is not None

        now = time.time()
        with self._lock:
            last = self._last_sent_by_key.get(key)
            if last is not None and (now - last) < min_interval_seconds:
                return False
            self._last_sent_by_key[key] = now

        prefix = _build_notification_prefix()
        text_to_send = f"{prefix} {text}".strip() if prefix else text

        attempted = False
        for chat_id in config.chat_ids:
            for chunk in _chunk_text(text_to_send):
                attempted = True
                try:
                    self._send_message(chat_id=chat_id, text=chunk)
                except Exception as exc:
                    if self._logger is not None:
                        self._logger.warning(f"No se pudo enviar notificación a chat_id={chat_id}: {exc}")
        return attempted

    def _send_message(self, *, chat_id: str, text: str) -> None:
        config = self._config
        assert config is not None

        url = f"{config.api_base}/bot{config.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=config.timeout_seconds) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            # Bot API devuelve JSON; si ok=false, lo consideramos error.
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("ok") is False:
                raise RuntimeError(f"Telegram Bot API error: {parsed}")


_notifier_singleton: Optional[TelegramBotNotifier] = None


def get_notifier(logger=None) -> TelegramBotNotifier:
    global _notifier_singleton
    if _notifier_singleton is None:
        _notifier_singleton = TelegramBotNotifier.from_env(logger=logger)
    return _notifier_singleton
