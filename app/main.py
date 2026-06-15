"""Panel web: estado de rutas, ofertas detectadas e histórico de precios."""

import json
from collections import defaultdict

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.db import Deal, PricePoint, SessionLocal, init_db, median_price
from app.worker import load_config

app = FastAPI(title="Vuelos Radar")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    cfg = load_config()
    session = SessionLocal()
    try:
        # Últimas ofertas
        deals = session.execute(
            select(Deal).order_by(Deal.created_at.desc()).limit(40)
        ).scalars().all()

        # Mejor precio actual y mediana por ruta
        routes = []
        for o in cfg["origins"]:
            for d in cfg["destinations"]:
                rows = session.execute(
                    select(PricePoint.price, PricePoint.observed_at)
                    .where(PricePoint.origin == o["code"],
                           PricePoint.destination == d["code"])
                    .order_by(PricePoint.observed_at.desc())
                    .limit(200)
                ).all()
                if not rows:
                    continue
                best = min(r[0] for r in rows)
                med = median_price(session, o["code"], d["code"],
                                   cfg["defaults"]["history_days"])
                # serie diaria (mínimo del día) para el sparkline
                by_day = defaultdict(list)
                for price, ts in rows:
                    by_day[ts.strftime("%m-%d")].append(price)
                series = [{"d": k, "p": min(v)} for k, v in sorted(by_day.items())][-30:]
                routes.append({
                    "origin": o["code"], "dest": d["code"],
                    "origin_city": o["city"], "dest_city": d["city"],
                    "best": best, "median": med, "series": series,
                })
        routes.sort(key=lambda r: (r["best"] / r["median"]) if r["median"] else 1)
    finally:
        session.close()

    from app.sources.google_flights import build_url

    def deal_url(x):
        if x.url:
            return x.url
        if x.travel_date:
            return build_url(x.origin, x.destination, x.travel_date, x.return_date)
        return ""

    return HTML_TEMPLATE.replace(
        "__ROUTES__", json.dumps(routes)
    ).replace(
        "__DEALS__", json.dumps([{
            "route": f"{x.origin} → {x.destination}",
            "price": x.price, "currency": x.currency,
            "median": x.median_ref, "source": x.source,
            "date": x.travel_date or "",
            "return_date": x.return_date or "",
            "when": x.created_at.strftime("%d/%m %H:%M") if x.created_at else "",
            "url": deal_url(x),
        } for x in deals])
    )


HTML_TEMPLATE = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vuelos Radar</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Archivo:wght@500;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#0b1020;--panel:#121a30;--line:#1f2a47;--ink:#e8ecf6;--dim:#8b96b3;--amber:#ffb454;--green:#4ade80;--red:#f87171}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--ink);font-family:'IBM Plex Mono',monospace;padding:24px;max-width:1100px;margin:auto}
h1{font-family:Archivo,sans-serif;font-weight:800;letter-spacing:-.5px;font-size:1.9rem}
h1 span{color:var(--amber)}
h2{font-family:Archivo,sans-serif;font-size:.85rem;text-transform:uppercase;letter-spacing:.15em;color:var(--dim);margin:34px 0 12px}
.sub{color:var(--dim);font-size:.8rem;margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);font-size:.82rem}
th{ text-align:left;color:var(--dim);font-weight:400;padding:10px 12px;border-bottom:1px solid var(--line);text-transform:uppercase;font-size:.68rem;letter-spacing:.1em}
td{padding:10px 12px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:none}
.price{color:var(--amber);font-weight:600}
.good{color:var(--green)} .bad{color:var(--red)}
.spark{width:120px;height:28px}
a{color:var(--amber)}
.badge{border:1px solid var(--line);border-radius:3px;padding:1px 6px;font-size:.68rem;color:var(--dim)}
@media(max-width:640px){.spark{width:70px}}
</style></head><body>
<h1>VUELOS<span>·</span>RADAR</h1>
<p class="sub">Monitoreo EZE / ASU / GRU / SCL → Europa · Google Flights + Travelpayouts + X</p>

<h2>Ofertas detectadas</h2>
<table><thead><tr><th>Ruta</th><th>Precio</th><th>Mediana</th><th>Ida</th><th>Vuelta</th><th>Fuente</th><th>Detectada</th></tr></thead>
<tbody id="deals"></tbody></table>

<h2>Estado por ruta</h2>
<table><thead><tr><th>Ruta</th><th>Mejor precio</th><th>Mediana 90d</th><th>vs mediana</th><th>Tendencia</th></tr></thead>
<tbody id="routes"></tbody></table>

<script>
const routes=__ROUTES__, deals=__DEALS__;
const fmt=n=>n?Math.round(n).toLocaleString('es'):'—';
document.getElementById('deals').innerHTML = deals.length ? deals.map(d=>`
<tr><td>${d.url?`<a href="${d.url}">${d.route} ↗</a>`:d.route}</td>
<td class="price">${fmt(d.price)} ${d.currency}</td><td>${fmt(d.median)}</td>
<td>${d.date||'—'}</td><td>${d.return_date||'—'}</td><td><span class="badge">${d.source}</span></td><td>${d.when}</td></tr>`).join('')
: '<tr><td colspan="7" style="color:var(--dim)">Sin ofertas todavía — el worker irá llenando esto.</td></tr>';

document.getElementById('routes').innerHTML = routes.length ? routes.map((r,i)=>{
  const diff=r.median?((r.best/r.median-1)*100):null;
  const cls=diff===null?'':(diff<0?'good':'bad');
  return `<tr><td>${r.origin_city} → ${r.dest_city}</td>
  <td class="price">${fmt(r.best)} USD</td><td>${fmt(r.median)}</td>
  <td class="${cls}">${diff===null?'—':(diff>0?'+':'')+diff.toFixed(0)+'%'}</td>
  <td><canvas class="spark" id="s${i}"></canvas></td></tr>`;
}).join('') : '<tr><td colspan="5" style="color:var(--dim)">Aún sin datos. Ejecuta el worker.</td></tr>';

routes.forEach((r,i)=>{
  const c=document.getElementById('s'+i); if(!c||!r.series.length)return;
  const ctx=c.getContext('2d'),W=c.width=c.offsetWidth*2,H=c.height=56;
  const ps=r.series.map(s=>s.p),min=Math.min(...ps),max=Math.max(...ps),rg=max-min||1;
  ctx.strokeStyle='#ffb454';ctx.lineWidth=2;ctx.beginPath();
  ps.forEach((p,j)=>{const x=j/(ps.length-1||1)*W,y=H-6-((p-min)/rg)*(H-12);
    j?ctx.lineTo(x,y):ctx.moveTo(x,y)});
  ctx.stroke();
});
</script></body></html>"""
