"""Detección de oportunidades: compara cada precio contra la mediana
histórica de la ruta y contra el tope absoluto configurado."""

import hashlib
import logging

from sqlalchemy.exc import IntegrityError

from app.db import Deal, median_price

log = logging.getLogger("opportunity")


def evaluate(session, point: dict, cfg: dict) -> Deal | None:
    """point: {origin, destination, travel_date, price, currency, source, url, ...}
    Devuelve un Deal nuevo si es oportunidad (y no estaba ya registrada)."""
    origin, dest = point["origin"], point["destination"]
    price = point["price"]

    origin_cfg = next((o for o in cfg["origins"] if o["code"] == origin), {})
    cap = origin_cfg.get("max_price_usd")
    pct = cfg["defaults"]["pct_below_median"]
    history_days = cfg["defaults"]["history_days"]

    median = median_price(session, origin, dest, history_days)

    reason = None
    if cap and point.get("currency", "USD") == "USD" and price <= cap:
        reason = "below_cap"
    if median and price <= median * (1 - pct):
        reason = "pct_below_median"
    if point["source"] == "x" and reason is None:
        # Una cuenta especializada ya lo consideró chollo: lo registramos
        # como candidato si además baja de la mediana aunque sea un poco.
        if median is None or price <= median:
            reason = "x_post"
    if reason is None:
        return None

    # Dedupe: misma ruta + mes de viaje + franja de precio (±5%)
    bucket = int(price / max(price * 0.05, 10))
    key_src = f"{origin}-{dest}-{(point.get('travel_date') or '')[:7]}-{bucket}"
    dedupe_key = hashlib.sha1(key_src.encode()).hexdigest()[:32]

    deal = Deal(
        origin=origin,
        destination=dest,
        travel_date=point.get("travel_date"),
        return_date=point.get("return_date"),
        price=price,
        currency=point.get("currency", "USD"),
        median_ref=median,
        source=point["source"],
        reason=reason,
        detail=point.get("detail"),
        url=point.get("url"),
        dedupe_key=dedupe_key,
    )
    session.add(deal)
    try:
        session.commit()
        return deal
    except IntegrityError:
        session.rollback()  # ya alertada
        return None
