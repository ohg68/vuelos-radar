"""Worker principal — lo ejecuta el cron de Railway cada 4-6 horas.

Flujo:
1. Google Flights (fli): calendario de precios por ruta → guarda histórico.
2. Travelpayouts: billetes más baratos por ruta → guarda histórico.
3. X: tweets nuevos de cuentas de chollos → Claude extrae ofertas.
4. Por cada precio nuevo, evalúa si es oportunidad → alerta por Telegram.
"""

import logging
import time
from pathlib import Path

import yaml

from app.db import PricePoint, SeenTweet, SessionLocal, init_db
from app.alerts.telegram import send_deal
from app.logic.opportunity import evaluate
from app.sources import google_flights, telegram_channels, travelpayouts, x_monitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("worker")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "routes.yaml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def ingest_and_alert(session, cfg, points: list[dict]):
    alerts = 0
    for p in points:
        session.add(PricePoint(
            origin=p["origin"], destination=p["destination"],
            travel_date=p.get("travel_date"), return_date=p.get("return_date"),
            trip_type=p.get("trip_type", cfg["defaults"]["trip_type"]),
            price=p["price"], currency=p.get("currency", "USD"),
            source=p["source"], airline=p.get("airline"), url=p.get("url"),
        ))
        session.commit()
        deal = evaluate(session, p, cfg)
        if deal:
            if send_deal(deal):
                alerts += 1
    return alerts


def run_flight_sources(session, cfg):
    d = cfg["defaults"]
    total_alerts = 0
    for o in cfg["origins"]:
        for dest in cfg["destinations"]:
            route = f"{o['code']}→{dest['code']}"

            # 1) Google Flights (calendario completo en 2-3 requests)
            cal = google_flights.fetch_calendar(
                o["code"], dest["code"],
                trip_type=d["trip_type"], stay_days=d["stay_days"],
                window_days=d["search_window_days"], currency=d["currency"],
            )
            # Solo guardamos los 5 más baratos del calendario: son los que importan
            cheapest = sorted(cal, key=lambda x: x["price"])[:5]
            pts = [{**c, "origin": o["code"], "destination": dest["code"],
                    "currency": d["currency"], "source": "google_flights"} for c in cheapest]
            total_alerts += ingest_and_alert(session, cfg, pts)
            log.info("%s google_flights: %d fechas, min %s",
                     route, len(cal), cheapest[0]["price"] if cheapest else "—")

            # 2) Travelpayouts
            tp = travelpayouts.fetch_cheapest(
                o["code"], dest["code"],
                trip_type=d["trip_type"], window_days=d["search_window_days"],
            )
            cheapest_tp = sorted(tp, key=lambda x: x["price"])[:5]
            pts = [{**c, "origin": o["code"], "destination": dest["code"],
                    "currency": "USD", "source": "travelpayouts"} for c in cheapest_tp]
            total_alerts += ingest_and_alert(session, cfg, pts)
            log.info("%s travelpayouts: %d resultados", route, len(tp))

            time.sleep(2)  # respiro entre rutas
    return total_alerts


def run_x_source(session, cfg):
    accounts = cfg.get("x_accounts", [])
    if not accounts:
        return 0
    tweets = x_monitor.fetch_tweets(accounts)
    valid_dests = {d["code"] for d in cfg["destinations"]}
    valid_origins = {o["code"] for o in cfg["origins"]}
    alerts = 0

    for t in tweets:
        if session.query(SeenTweet).filter_by(tweet_id=t["tweet_id"]).first():
            continue
        session.add(SeenTweet(tweet_id=t["tweet_id"], account=t["account"]))
        session.commit()

        for deal in x_monitor.parse_tweet(t["account"], t["text"]):
            origin = deal.get("origin_iata", "")
            dest = deal.get("destination_iata", "")
            if origin not in valid_origins or dest not in valid_dests:
                continue
            p = {
                "origin": origin, "destination": dest,
                "travel_date": None, "price": float(deal["price"]),
                "currency": deal.get("currency", "USD"),
                "source": "x", "url": t["url"],
                "detail": f"@{t['account']}: {t['text'][:200]}",
            }
            alerts += ingest_and_alert(session, cfg, [p])
    return alerts


def run_telegram_source(session, cfg):
    """Canales públicos de Telegram — gratis, sin API."""
    channels = cfg.get("telegram_channels", [])
    if not channels:
        return 0
    valid_dests = {d["code"] for d in cfg["destinations"]}
    valid_origins = {o["code"] for o in cfg["origins"]}
    alerts = 0

    for ch in channels:
        for m in telegram_channels.fetch_messages(ch):
            if session.query(SeenTweet).filter_by(tweet_id=m["msg_id"]).first():
                continue
            session.add(SeenTweet(tweet_id=m["msg_id"], account=m["channel"]))
            session.commit()

            for deal in telegram_channels.parse_message(m["channel"], m["text"]):
                origin = deal.get("origin_iata", "")
                dest = deal.get("destination_iata", "")
                if origin not in valid_origins or dest not in valid_dests:
                    continue
                p = {
                    "origin": origin, "destination": dest,
                    "travel_date": None, "price": float(deal["price"]),
                    "currency": deal.get("currency", "USD"),
                    "source": "telegram", "url": m["url"],
                    "detail": f"t.me/{m['channel']}: {m['text'][:200]}",
                }
                alerts += ingest_and_alert(session, cfg, [p])
    return alerts


def main():
    init_db()
    cfg = load_config()
    session = SessionLocal()
    try:
        a1 = run_flight_sources(session, cfg)
        a2 = run_telegram_source(session, cfg)
        a3 = run_x_source(session, cfg)
        log.info("Ciclo completo: %d alertas enviadas", a1 + a2 + a3)
    finally:
        session.close()


if __name__ == "__main__":
    main()
