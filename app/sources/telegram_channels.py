"""Fuente: canales públicos de Telegram con ofertas de vuelos.

No requiere API ni bot: los canales públicos exponen una vista web en
https://t.me/s/<canal> con los ~20 mensajes más recientes. Se parsea el
HTML y Claude Haiku extrae ruta + precio de cada mensaje nuevo.
"""

import html
import logging
import re

import httpx

from app.sources.x_monitor import parse_tweet  # mismo parser LLM, reutilizado

log = logging.getLogger("telegram_channels")

MSG_RE = re.compile(
    r'data-post="([^"]+)".*?class="tgme_widget_message_text[^>]*>(.*?)</div>',
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")


def fetch_messages(channel: str) -> list[dict]:
    """Devuelve [{msg_id, channel, text, url}] de los mensajes recientes."""
    try:
        r = httpx.get(
            f"https://t.me/s/{channel}",
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo leer t.me/s/%s: %s", channel, exc)
        return []

    out = []
    for post_id, raw in MSG_RE.findall(r.text):
        text = html.unescape(TAG_RE.sub(" ", raw))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 15:
            continue
        out.append({
            "msg_id": f"tg:{post_id}",          # ej. tg:turismocityar/12345
            "channel": channel,
            "text": text,
            "url": f"https://t.me/{post_id}",
        })
    return out


def parse_message(channel: str, text: str) -> list[dict]:
    """Extrae ofertas estructuradas (reutiliza el parser de Claude Haiku)."""
    return parse_tweet(channel, text)
