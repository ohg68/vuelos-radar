"""Fuente: Travelpayouts (datos de Aviasales) — API gratuita con token.

Regístrate en https://www.travelpayouts.com → API token → variable de
entorno TRAVELPAYOUTS_TOKEN. Endpoint usado: prices_for_dates (v3),
que devuelve los billetes más baratos encontrados en búsquedas reales
de usuarios de Aviasales (caché de ~48h, suficiente para detectar chollos).
"""

import logging
import os
from datetime import date, timedelta

import httpx

log = logging.getLogger("travelpayouts")

BASE = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def fetch_cheapest(
    origin: str,
    destination: str,
    trip_type: str = "round_trip",
    window_days: int = 150,
    currency: str = "usd",
) -> list[dict]:
    """Devuelve [{travel_date, return_date, price, airline, url}]."""
    token = os.getenv("TRAVELPAYOUTS_TOKEN")
    if not token:
        log.info("TRAVELPAYOUTS_TOKEN no definido; se omite esta fuente")
        return []

    out: list[dict] = []
    today = date.today()
    # La API filtra por mes de salida → consultamos cada mes de la ventana.
    months = set()
    for d in range(0, window_days, 28):
        months.add((today + timedelta(days=d)).strftime("%Y-%m"))

    with httpx.Client(timeout=30) as client:
        for month in sorted(months):
            params = {
                "origin": origin,
                "destination": destination,
                "departure_at": month,
                "one_way": "true" if trip_type == "one_way" else "false",
                "unique": "false",
                "sorting": "price",
                "limit": 10,
                "currency": currency,
                "token": token,
            }
            try:
                r = client.get(BASE, params=params)
                r.raise_for_status()
                data = r.json().get("data", [])
            except Exception as exc:  # noqa: BLE001
                log.warning("travelpayouts %s→%s %s: %s", origin, destination, month, exc)
                continue

            for item in data:
                out.append({
                    "travel_date": (item.get("departure_at") or "")[:10],
                    "return_date": (item.get("return_at") or "")[:10] or None,
                    "price": float(item["price"]),
                    "airline": item.get("airline"),
                    "url": "https://www.aviasales.com" + item["link"] if item.get("link") else None,
                })
    return out
