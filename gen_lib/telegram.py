"""
gen_lib/telegram.py — send images / videos / messages to a Telegram bot.

Replaces the old external /root/scripts/tg shell script. Reads credentials from
the project-root .env (loaded by common.load_env):

    TG_BOT_TOKEN=123456:ABC...   (bot token)
    TG_CHAT_ID=123456789         (target chat)

Everything the old shell script did is reproduced here in pure Python using
urllib, so gallery_server.py no longer shells out to an external script.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

from gen_lib.common import load_env

load_env()  # ensure project-root .env is loaded before reading TG_*


class TelegramError(RuntimeError):
    """Raised when a Telegram API call fails or is not configured."""


def _bot() -> tuple[str, str]:
    token = os.environ.get("TG_BOT_TOKEN", "").strip().strip('"').strip("'")
    chat_id = os.environ.get("TG_CHAT_ID", "").strip().strip('"').strip("'")
    if not token:
        raise TelegramError("TG_BOT_TOKEN not set in .env")
    if not chat_id:
        raise TelegramError("TG_CHAT_ID not set in .env")
    return token, chat_id


def _api(method: str, *, data: dict | None = None,
         multipart: dict[str, tuple[str, bytes | None, str]] | None = None,
         timeout: int = 120) -> None:
    """POST to a Telegram bot API method. Returns None; raises TelegramError on failure."""
    token, chat_id = _bot()
    url = f"https://api.telegram.org/bot{token}/{method}"
    headers = {}
    body = None

    # chat_id comes from _bot() (quotes stripped). Normalise any raw env usage
    # in the callers so the id is always clean.
    if multipart and "chat_id" in multipart:
        multipart["chat_id"] = (chat_id, None, "")
    if data and "chat_id" in data:
        data["chat_id"] = chat_id

    # Clean multipart build (kept simple & correct):
    if multipart:
        boundary = "----genboundary" + os.urandom(8).hex()
        buf = bytearray()
        for field, (fname, content, ctype) in multipart.items():
            if content is None:
                buf += f"--{boundary}\r\n".encode()
                buf += f'Content-Disposition: form-data; name="{field}"\r\n\r\n'.encode()
                buf += str(fname).encode() + b"\r\n"
            else:
                buf += f"--{boundary}\r\n".encode()
                buf += f'Content-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'.encode()
                buf += f"Content-Type: {ctype}\r\n\r\n".encode()
                buf += content + b"\r\n"
        buf += f"--{boundary}--\r\n".encode()
        body = bytes(buf)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise TelegramError(f"Telegram {method} HTTP {e.code}: {e.read()[:300]}") from e
    except urllib.error.URLError as e:
        raise TelegramError(f"Telegram {method} network error: {e}") from e

    if not result.get("ok"):
        raise TelegramError(f"Telegram {method} failed: {result.get('description', result)}")


_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "mp4": "video/mp4",
    "mov": "video/quicktime", "avi": "video/x-msvideo", "mkv": "video/x-matroska",
}


def _ctype(p: Path, default: str) -> str:
    return _MIME.get(p.suffix.lower().lstrip("."), default)


def send_photo(path: str | Path, caption: str = "") -> None:
    """Send a photo file."""
    p = Path(path)
    _api("sendPhoto", multipart={
        "chat_id": (str(os.environ["TG_CHAT_ID"]), None, ""),
        "photo": (p.name, p.read_bytes(), _ctype(p, "image/png")),
        "caption": (caption, None, ""),
    }, timeout=120)


def send_video(path: str | Path, caption: str = "") -> None:
    p = Path(path)
    _api("sendVideo", multipart={
        "chat_id": (str(os.environ["TG_CHAT_ID"]), None, ""),
        "video": (p.name, p.read_bytes(), _ctype(p, "video/mp4")),
        "caption": (caption, None, ""),
    }, timeout=300)


def send_document(path: str | Path, caption: str = "") -> None:
    p = Path(path)
    _api("sendDocument", multipart={
        "chat_id": (str(os.environ["TG_CHAT_ID"]), None, ""),
        "document": (p.name, p.read_bytes(), "application/octet-stream"),
        "caption": (caption, None, ""),
    }, timeout=180)


def send_message(text: str) -> None:
    _api("sendMessage", data={
        "chat_id": os.environ["TG_CHAT_ID"],
        "text": text,
        "parse_mode": "Markdown",
    }, timeout=60)


def send_file(path: str | Path, caption: str = "") -> str:
    """Send an arbitrary file, picking photo/video/document by extension.
    Returns '' on success; raises TelegramError on failure."""
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    if ext in ("jpg", "jpeg", "png", "gif", "webp"):
        send_photo(p, caption)
    elif ext in ("mp4", "mov", "avi", "mkv"):
        send_video(p, caption)
    else:
        send_document(p, caption)
    return ""
