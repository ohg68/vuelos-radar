"""Fuente: cuentas de X que publican ofertas de vuelos.

Lee los tweets recientes de las cuentas configuradas (X API v2, requiere
X_BEARER_TOKEN — plan Basic o superior para leer timelines) y usa Claude
Haiku para extraer ruta, precio y fechas en JSON estructurado.

Si no hay X_BEARER_TOKEN, la fuente se omite sin romper el worker.
"""

import json
import logging
import os

import httpx

log = logging.getLogger("x_monitor")

X_API = "https://api.twitter.com/2"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"

PARSE_PROMPT = """Eres un extractor de ofertas de vuelos. Analiza este tweet y \
devuelve SOLO un JSON (sin markdown, sin explicación) con este formato:
{{"deals": [{{"origin_iata": "EZE", "destination_iata": "MAD", \
"price": 650, "currency": "USD", "travel_dates": "texto de fechas o null", \
"is_flight_deal": true}}]}}

Reglas:
- Si el tweet NO es una oferta concreta de vuelo con precio, devuelve {{"deals": []}}
- Convierte ciudades a códigos IATA del aeropuerto principal (Buenos Aires=EZE, \
Asunción=ASU, São Paulo=GRU, Santiago=SCL, Madrid=MAD, Barcelona=BCN, París=CDG, \
Roma=FCO, Lisboa=LIS, Atenas=ATH, Tesalónica=SKG).
- Si el precio está en ARS, BRL, CLP o EUR, mantén la moneda original.

Tweet de @{account}:
{text}"""


def _get_user_ids(client: httpx.Client, accounts: list[str], headers: dict) -> dict:
    r = client.get(
        f"{X_API}/users/by",
        params={"usernames": ",".join(accounts)},
        headers=headers,
    )
    r.raise_for_status()
    return {u["username"].lower(): u["id"] for u in r.json().get("data", [])}


def fetch_tweets(accounts: list[str], max_per_account: int = 15) -> list[dict]:
    """Devuelve [{tweet_id, account, text, url}] de tweets recientes."""
    token = os.getenv("X_BEARER_TOKEN")
    if not token:
        log.info("X_BEARER_TOKEN no definido; se omite el monitoreo de X")
        return []

    headers = {"Authorization": f"Bearer {token}"}
    out: list[dict] = []
    with httpx.Client(timeout=30) as client:
        try:
            ids = _get_user_ids(client, accounts, headers)
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudieron resolver cuentas de X: %s", exc)
            return []

        for account, uid in ids.items():
            try:
                r = client.get(
                    f"{X_API}/users/{uid}/tweets",
                    params={"max_results": max_per_account, "exclude": "retweets,replies"},
                    headers=headers,
                )
                r.raise_for_status()
                for t in r.json().get("data", []):
                    out.append({
                        "tweet_id": t["id"],
                        "account": account,
                        "text": t["text"],
                        "url": f"https://x.com/{account}/status/{t['id']}",
                    })
            except Exception as exc:  # noqa: BLE001
                log.warning("Error leyendo @%s: %s", account, exc)
    return out


def parse_tweet(account: str, text: str) -> list[dict]:
    """Extrae ofertas estructuradas de un tweet usando Claude Haiku."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.info("ANTHROPIC_API_KEY no definido; no se pueden parsear tweets")
        return []

    body = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 500,
        "messages": [
            {"role": "user", "content": PARSE_PROMPT.format(account=account, text=text)}
        ],
    }
    try:
        r = httpx.post(
            ANTHROPIC_API,
            json=body,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=30,
        )
        r.raise_for_status()
        raw = "".join(b.get("text", "") for b in r.json()["content"])
        raw = raw.replace("```json", "").replace("```", "").strip()
        deals = json.loads(raw).get("deals", [])
        return [d for d in deals if d.get("is_flight_deal") and d.get("price")]
    except Exception as exc:  # noqa: BLE001
        log.warning("Parser falló para tweet de @%s: %s", account, exc)
        return []
