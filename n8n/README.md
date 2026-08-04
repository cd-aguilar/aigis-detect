# Workflow n8n — Wazuh → agente → TheHive/Slack/Telegram

`workflows/wazuh-triage-to-thehive.json` conecta el SIEM con el SOAR: cada 15
minutos busca alertas nuevas en Elasticsearch, las manda al agente de triage
(Fase 2), crea una alerta en TheHive con el veredicto, y notifica por Slack
(siempre) y Telegram (solo alta/crítica severidad).

El intervalo es de 15 min (no 2) y el procesamiento es estrictamente
secuencial (1 alerta a la vez, hasta 5 por ciclo) a propósito: `qwen3` en CPU
tarda 5-10 min por alerta (ver `CLAUDE.md`), y un cron más agresivo o sin
límite de items hace que las ejecuciones se apilen — pasó de verdad probando
esto, ver la nota al final de este archivo.

## Flujo

1. **Cada 15 minutos** (Schedule Trigger).
2. **Redis - intentar lock de ejecución** / **Ejecución en curso?** — lock a
   nivel de workflow completo, ver "Lock contra ejecuciones solapadas" abajo.
   Si ya hay un ciclo corriendo, esta ejecución nueva termina de inmediato en
   **Fin - ejecución solapada** (NoOp) sin tocar Elastic ni el agente.
3. **Redis - marcar lock de ejecución** (TTL 2h, red de seguridad por si el
   ciclo nunca llega a liberar el lock explícitamente) → recién acá arranca
   el flujo original.
4. **Buscar alertas nuevas en Elastic** — `POST /wazuh-alerts-*/_search`,
   ventana `now-16m` (1 min de solapamiento contra jitter del cron), `size: 5`
   (tope duro en la propia query, además del nodo Limit del paso 6).
5. **Separar alertas** — un item por hit.
6. **Limitar items por ejecución** (Limit, `maxItems: 5`) — tope explícito
   independiente del `size` de la query, por si alguien lo cambia más adelante.
7. **Loop Over Items** (Split In Batches, `batchSize: 1`) — procesa una
   alerta a la vez: cada una hace su recorrido completo (dedup → agente →
   TheHive → Slack → Telegram) antes de que arranque la siguiente. Todos los
   caminos de salida del flujo (alerta ya procesada, severidad normal,
   severidad alta) vuelven a conectar acá para pedir el siguiente item —
   si tocás el workflow, no rompas ese loop-back o el ciclo se corta en el
   primer item.
8. **Redis - ya procesada?** / **Ya procesada?** — dedup por `_id` de la
   alerta, para no reprocesar si el cron se solapa con un triage largo.
9. **Redis - marcar procesada** — TTL 24h.
10. **Armar AlertInput** → **Llamar agente /triage** (`POST agent:8080/triage`,
    timeout de 40 min seteado en el nodo — subido desde 15 min porque una
    alerta real con 2 vueltas de tool-calling tardó ~16 min y el timeout
    anterior cortaba la conexión con un error falso (el agente sí terminaba bien)).
11. **Mapear severidad TheHive** — `low/medium/high/critical` → escala 1-4.
12. **Crear alerta en TheHive** — `POST /api/v1/alert`, tipo `external`,
    `sourceRef` = id de la alerta de Wazuh (evita duplicados si TheHive ya la
    tiene), veredicto/explicación/acción sugerida en la descripción, técnica
    MITRE como tag.
13. **Slack - log completo** — todas las alertas, sin filtrar.
14. **Es alta severidad?** → **Telegram - alta severidad** — solo si el
    agente devolvió `high` o `critical`. La rama de severidad normal termina
    en **Fin - severidad normal** (NoOp), solo para volver al loop.
15. **Redis - liberar lock de ejecución** → **Fin del ciclo** (NoOp) — se
    dispara una vez cuando el Loop Over Items ya no tiene más items para
    procesar (incluido el caso de 0 alertas nuevas), y libera el lock del
    paso 2 para que el próximo disparo del cron pueda entrar.

## Lock contra ejecuciones solapadas

Ya cerrado (antes era el único pendiente documentado acá). Con el intervalo
de 15 min y tope de 5 items esto era poco probable en este homelab, pero si
el triage de una alerta tarda más de 15 min (pasó de verdad — ver el timeout
de 40 min del paso 10), el próximo disparo del Schedule Trigger podía
arrancar una ejecución nueva en paralelo, duplicando triages/alertas en
TheHive.

Patrón: `GET aigis:workflow:lock` en Redis → IF vacío (sin lock) → `SET
aigis:workflow:lock 1 TTL 7200` → sigue el flujo normal. Si el valor no está
vacío (lock tomado por otra ejecución), la ejecución nueva corta de inmediato
en **Fin - ejecución solapada**. El lock se libera explícitamente al final
del ciclo (**Redis - liberar lock de ejecución**, antes de **Fin del
ciclo**); el TTL de 2h es solo la red de seguridad para el caso raro de que
la ejecución se corte a mitad de camino sin llegar a esa liberación (crash,
reinicio del contenedor n8n, etc.) — sin el TTL, un lock huérfano dejaría el
workflow bloqueado para siempre.

Mismo patrón check-then-set (no atómico) que ya usaba el dedup por `_id` de
alerta (**Redis - ya procesada?** / **Redis - marcar procesada**) — hay una
ventana de carrera teórica entre el `GET` y el `SET`, pero es aceptable acá:
el intervalo mínimo entre disparos es 15 min, muy por encima de la latencia
de ida y vuelta a Redis.

## Cómo importar

1. Abrí n8n (http://localhost:5678) → menú (⋮) → **Import from File** →
   seleccioná `workflows/wazuh-triage-to-thehive.json`.
2. Los 5 nodos Redis (**Redis - ya procesada?**, **Redis - marcar
   procesada**, **Redis - intentar lock de ejecución**, **Redis - marcar
   lock de ejecución**, **Redis - liberar lock de ejecución**) van a pedir
   credencial. Creá una credencial de tipo **Redis** (una sola vez): host
   `redis`, puerto `6379`, sin password (así está el servicio en
   `docker-compose.yml`). Asignala a los 5.
3. Completá en tu `.env` (raíz del proyecto, no dentro de n8n):
   `THEHIVE_API_KEY`, `SLACK_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID_ONCALL` — el workflow los lee vía `$env.*`, no hace
   falta cargarlos en la UI de n8n.
   - `THEHIVE_API_KEY`: TheHive → tu usuario (arriba a la derecha) →
     **Create API key**.
   - `SLACK_WEBHOOK_URL`: app "Incoming Webhooks" en tu workspace de Slack.
   - `TELEGRAM_BOT_TOKEN`: hablale a `@BotFather` en Telegram, `/newbot`.
   - `TELEGRAM_CHAT_ID_ONCALL`: chat_id del canal/chat donde querés las
     alertas de alta severidad (podés sacarlo pegándole `/start` al bot y
     consultando `https://api.telegram.org/bot<token>/getUpdates`).
4. `docker compose up -d n8n` (o recreá el contenedor si ya estaba arriba,
   para que tome las env vars nuevas).
5. Activá el workflow (toggle arriba a la derecha) cuando quieras que corra solo.

**Si ya tenías este workflow importado y activo** (como en este proyecto,
desde el cierre de Telegram): reimportar el archivo actualiza el "draft" del
workflow, pero esta versión de n8n (2.32.5) corre la versión publicada
(`activeVersionId`), no el draft — un workflow activo puede seguir
ejecutando los nodos viejos aunque el canvas muestre los nuevos. Después de
importar, asigná la credencial Redis a los 3 nodos nuevos y volvé a
**guardar y activar/publicar** el workflow desde la UI (no alcanza con que
el canvas se vea bien) antes de dar por hecho que el lock ya está en
efecto — confirmalo viendo pasar al menos una ejecución real en
**Executions** con los nodos del lock adentro.

## Nota sobre versiones de n8n

Este workflow ya se importó y se corrió (manualmente, sin activar el cron)
contra una instancia real de n8n 2.32.5 — entró sin ningún error de
`typeVersion` en los 18 nodos originales (23 desde que se agregó el lock).
Si tu versión de n8n es muy distinta y algún
nodo aparece con ícono de advertencia al importar, abrilo: n8n suele ofrecer
actualizar el `typeVersion` automáticamente sin perder la lógica.

Para pruebas manuales sin esperar una alerta real de Wazuh: el nodo
**Buscar alertas nuevas en Elastic** tiene la ventana en `now-16m`; si querés
forzar que tome alertas viejas para probar el resto del flujo, cambiala
temporalmente (ej. `now-24h`) — pero recordá que igual **solo entran 5 items
por ejecución** (Limit + `size` de la query) y se procesan de a uno
(Loop Over Items), así que el peor caso queda acotado a ~5 triages
seguidos (25-50 min), no a horas. Revertí la ventana a `now-16m` después.
