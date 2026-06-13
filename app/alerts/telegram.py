"""Alertas por Telegram.

Crea un bot con @BotFather → TELEGRAM_BOT_TOKEN.
Escríbele un mensaje al bot y obtén tu chat_id en
https://api.telegram.org/bot<TOKEN>/getUpdates → TELEGRAM_CHAT_ID.
"""

import logging
import os

import httpx

log = logging.getLogger("telegram")

CITY = {
    "EZE": "Buenos Aires", "ASU": "Asunción", "GRU": "São Paulo",
    "SCL": "Santiago", "MAD": "Madrid", "BCN": "Barcelona", "CDG": "París",
    "FCO": "Roma", "LIS": "Lisboa", "ATH": "Atenas", "SKG": "Tesalónica",
}

REASON_TXT = {
    "below_cap": "por debajo de tu tope",
    "pct_below_median": "muy por debajo de la mediana histórica",
    "x_post": "publicada en X",
}


def send_deal(deal) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("Telegram no configurado; alerta no enviada")
        return False

    o = CITY.get(deal.origin, deal.origin)
    d = CITY.get(deal.destination, deal.destination)
    lines = [
        f"✈️ <b>{o} → {d}</b>",
        f"💰 <b>{deal.price:.0f} {deal.currency}</b>"
        + (f" (mediana: {deal.median_ref:.0f})" if deal.median_ref else ""),
    ]
    if deal.travel_date:
        lines.append(f"📅 Salida: {deal.travel_date}")
    lines.append(f"🔎 Fuente: {deal.source} · {REASON_TXT.get(deal.reason, deal.reason)}")
    if deal.detail:
        lines.append(f"📝 {deal.detail[:300]}")
    if deal.url:
        lines.append(f'<a href="{deal.url}">Ver oferta</a>')

    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "\n".join(lines),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Error enviando Telegram: %s", exc)
        return False
