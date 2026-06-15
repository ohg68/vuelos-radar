"""Base de datos: histórico de precios, ofertas detectadas y tweets procesados.

Usa DATABASE_URL (PostgreSQL en Neon/Railway). Si no está definida,
cae a SQLite local para desarrollo.
"""

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text, create_engine, func, select,
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///vuelos.db")
# Railway/Heroku a veces entregan postgres:// en lugar de postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class PricePoint(Base):
    """Cada observación de precio de cualquier fuente."""

    __tablename__ = "price_points"

    id = Column(Integer, primary_key=True)
    origin = Column(String(3), index=True, nullable=False)
    destination = Column(String(3), index=True, nullable=False)
    travel_date = Column(String(10))           # YYYY-MM-DD (fecha de salida)
    return_date = Column(String(10), nullable=True)
    trip_type = Column(String(12), default="round_trip")
    price = Column(Float, nullable=False)
    currency = Column(String(3), default="USD")
    source = Column(String(24), nullable=False)  # google_flights | travelpayouts | x
    airline = Column(String(80), nullable=True)
    url = Column(Text, nullable=True)
    observed_at = Column(DateTime(timezone=True), default=utcnow, index=True)


class Deal(Base):
    """Oportunidades que dispararon alerta (para dedupe y dashboard)."""

    __tablename__ = "deals"

    id = Column(Integer, primary_key=True)
    origin = Column(String(3), index=True)
    destination = Column(String(3), index=True)
    travel_date = Column(String(10))
    return_date = Column(String(10), nullable=True)
    price = Column(Float)
    currency = Column(String(3), default="USD")
    median_ref = Column(Float, nullable=True)   # mediana vigente al detectar
    source = Column(String(24))
    reason = Column(String(40))                 # pct_below_median | below_cap | x_post
    detail = Column(Text, nullable=True)
    url = Column(Text, nullable=True)
    dedupe_key = Column(String(120), unique=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class SeenTweet(Base):
    """Tweets ya procesados para no repetir alertas."""

    __tablename__ = "seen_tweets"

    id = Column(Integer, primary_key=True)
    tweet_id = Column(String(120), unique=True, index=True)
    account = Column(String(60))
    processed_at = Column(DateTime(timezone=True), default=utcnow)


def init_db():
    Base.metadata.create_all(engine)
    _run_migrations()


def _run_migrations():
    """Ajustes idempotentes sobre tablas ya existentes (create_all no altera columnas).

    Amplía campos que en versiones previas eran demasiado cortos. Seguro de
    ejecutar en cada arranque: si la columna ya tiene el tamaño correcto, no hace nada.
    """
    from sqlalchemy import text

    stmts = [
        "ALTER TABLE seen_tweets ALTER COLUMN tweet_id TYPE VARCHAR(120)",
        "ALTER TABLE seen_tweets ALTER COLUMN account TYPE VARCHAR(60)",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS return_date VARCHAR(10)",
    ]
    # Solo aplica en PostgreSQL; SQLite no necesita (y no soporta) estos ALTER.
    if not DATABASE_URL.startswith("postgresql"):
        return
    with engine.begin() as conn:
        for s in stmts:
            try:
                conn.execute(text(s))
            except Exception:
                pass  # columna ya correcta o tabla aún no creada


def median_price(session, origin: str, destination: str, history_days: int = 90):
    """Mediana de precios observados para una ruta (últimas ~2000 observaciones).

    Implementación portable (SQLite no tiene percentile): traemos y calculamos.
    """
    from datetime import timedelta

    cutoff = utcnow() - timedelta(days=history_days)
    rows = session.execute(
        select(PricePoint.price)
        .where(
            PricePoint.origin == origin,
            PricePoint.destination == destination,
            PricePoint.observed_at >= cutoff,
        )
        .order_by(PricePoint.observed_at.desc())
        .limit(2000)
    ).scalars().all()
    if not rows:
        return None
    rows = sorted(rows)
    n = len(rows)
    mid = n // 2
    return rows[mid] if n % 2 else (rows[mid - 1] + rows[mid]) / 2
