# Vuelos Radar ✈️

Monitor de oportunidades de vuelos económicos hacia Europa desde
**Buenos Aires (EZE), Asunción (ASU), São Paulo (GRU) y Santiago (SCL)**,
con alertas por Telegram.

## Fuentes

| Fuente | Cómo | Requiere |
|---|---|---|
| Google Flights | Librería `fli` (calendario de precios, ~3 requests por ruta) | Nada |
| Travelpayouts/Aviasales | API oficial gratuita de precios baratos | Token gratis |
| Cuentas de X | X API v2 + Claude Haiku extrae ruta/precio del tweet | X API Basic + ANTHROPIC_API_KEY |

## Lógica de oportunidad

Cada precio observado se guarda en PostgreSQL. Se alerta cuando:
1. El precio está **≥25% por debajo de la mediana** de los últimos 90 días de esa ruta, o
2. Baja del **tope absoluto** configurado por origen (ej. EZE < 800 USD i/v), o
3. Una cuenta de chollos lo publicó en X y no supera la mediana.

Hay deduplicación: la misma oferta (ruta + mes + franja de precio) solo alerta una vez.

## Despliegue en Railway

1. Sube este repo a GitHub y crea un proyecto en Railway desde el repo.
2. Añade un servicio **PostgreSQL** (Railway lo inyecta como `DATABASE_URL`).
3. Variables de entorno (ver `.env.example`):
   - `TELEGRAM_BOT_TOKEN`: crea un bot con @BotFather.
   - `TELEGRAM_CHAT_ID`: escribe al bot y mira `https://api.telegram.org/bot<TOKEN>/getUpdates`.
   - `TRAVELPAYOUTS_TOKEN`: gratis en travelpayouts.com.
   - `X_BEARER_TOKEN` y `ANTHROPIC_API_KEY`: solo si activas el monitoreo de X.
4. El servicio web (dashboard) arranca solo con `railway.json`.
5. **Cron del worker**: crea un segundo servicio en el mismo repo con
   start command `python -m app.worker` y en Settings → Cron Schedule:
   `0 */5 * * *` (cada 5 horas).

## Ajustes

Todo se configura en `config/routes.yaml`: orígenes, destinos, topes por
origen, % bajo mediana, duración del viaje (ida y vuelta, 14 días por
defecto) y las cuentas de X a vigilar.

## Notas

- Los primeros días no hay mediana histórica: solo alertan los precios
  bajo el tope absoluto. La detección por mediana mejora sola con el tiempo.
- Si Google bloquea la IP del datacenter (devuelve vacío sin error), el
  worker lo registra en logs y sigue con Travelpayouts. Suele bastar con
  redeplegar para rotar de IP.
- Si X API Basic no te compensa (199 USD/mes), alternativa: suscribirte a
  los canales de Telegram de esas mismas cuentas (Turismocity y Melhores
  Destinos tienen canal propio) y dejar X fuera.

## Dashboard

`/` muestra ofertas detectadas, mejor precio actual vs mediana por ruta
y tendencia (sparkline de 30 días). `/health` para el healthcheck.
