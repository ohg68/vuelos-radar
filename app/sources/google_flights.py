"""Fuente: Google Flights vía la librería `fli` (paquete PyPI: flights).

Usa el endpoint de calendario (GetCalendarGraph) que devuelve el precio
más barato por fecha de salida en una ventana — una sola petición cubre
~60 días, así que el volumen de requests es muy bajo.

Nota: Google bloquea algunas IPs de datacenter. Si devuelve None de forma
persistente, el worker lo registra y sigue con Travelpayouts.
"""

import logging
from datetime import date, timedelta
from urllib.parse import quote

from fli.models import (
    Airport, DateSearchFilters, FlightSegment, PassengerInfo, SeatType, TripType,
)
from fli.search import SearchDates

log = logging.getLogger("google_flights")


def build_url(origin: str, destination: str, travel_date: str,
              return_date: str | None = None) -> str:
    """Construye un enlace de búsqueda de Google Flights que abre el resultado.

    Usa la sintaxis de URL de texto de Google Flights, que prefiltra origen,
    destino y fechas. Funciona tanto para ida y vuelta como para solo ida.
    """
    if return_date:
        q = (f"Flights from {origin} to {destination} "
             f"on {travel_date} returning {return_date}")
    else:
        q = f"Flights from {origin} to {destination} on {travel_date}"
    return f"https://www.google.com/travel/flights?q={quote(q)}"


def fetch_calendar(
    origin: str,
    destination: str,
    trip_type: str = "round_trip",
    stay_days: int = 14,
    window_days: int = 150,
    currency: str = "USD",
) -> list[dict]:
    """Devuelve [{travel_date, return_date, price, url}] para una ruta."""
    today = date.today()
    from_date = today + timedelta(days=3)
    to_date = today + timedelta(days=min(window_days, 300))

    tt = TripType.ROUND_TRIP if trip_type == "round_trip" else TripType.ONE_WAY

    segments = [
        FlightSegment(
            departure_airport=[[Airport[origin], 0]],
            arrival_airport=[[Airport[destination], 0]],
            travel_date=(from_date + timedelta(days=7)).isoformat(),
        )
    ]
    if tt == TripType.ROUND_TRIP:
        segments.append(
            FlightSegment(
                departure_airport=[[Airport[destination], 0]],
                arrival_airport=[[Airport[origin], 0]],
                travel_date=(from_date + timedelta(days=7 + stay_days)).isoformat(),
            )
        )

    filters = DateSearchFilters(
        trip_type=tt,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=segments,
        seat_type=SeatType.ECONOMY,
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        duration=stay_days if tt == TripType.ROUND_TRIP else None,
    )

    try:
        results = SearchDates().search(filters, currency=currency)
    except Exception as exc:  # noqa: BLE001
        log.warning("fli falló %s→%s: %s", origin, destination, exc)
        return []

    if not results:
        log.warning("fli devolvió vacío %s→%s (¿IP bloqueada por Google?)", origin, destination)
        return []

    out = []
    for r in results:
        if r.price and r.price > 0:
            d = r.date[0] if isinstance(r.date, (list, tuple)) else r.date
            d = d.isoformat() if hasattr(d, "isoformat") else str(d)
            travel_date = d[:10]
            # En round_trip la consulta usa duration=stay_days, así que la
            # fecha de regreso es salida + stay_days (coincide con el precio real).
            ret = None
            if tt == TripType.ROUND_TRIP:
                ret = (date.fromisoformat(travel_date) + timedelta(days=stay_days)).isoformat()
            out.append({
                "travel_date": travel_date,
                "return_date": ret,
                "price": float(r.price),
                "url": build_url(origin, destination, travel_date, ret),
            })
    return out
