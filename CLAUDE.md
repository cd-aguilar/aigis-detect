# Contexto del proyecto — Aigis-Detect (SentinelAgent)

## Objetivo
SOC Lab Portfolio: homelab de ciberseguridad con SIEM (Elastic Stack), SOAR (n8n)
y un agente de triage con IA. Alimenta el portfolio en aigis-cloud.com/labs y
la búsqueda de roles en Detection Engineering / SOC Engineer / Security Automation.

## Stack
- **SIEM/Detección:** Elasticsearch, Kibana, Wazuh Manager (sin indexer nativo,
  forward vía Filebeat), Zircolite, Elastic Agent/Fleet
- **SOAR/Orquestación:** n8n, TheHive
- **DFIR:** Velociraptor
- **IA (Fase 2):** Ollama (Qwen3), ChromaDB, FastAPI, Streamlit (function calling
  nativo de Ollama en vez de LangChain — se suma LangChain solo si el nativo se
  queda corto, por la regla de ROI del proyecto)
- **Infra:** Docker Compose (Fase 1), Terraform + AWS (Fase 3), Redis (dedup de alertas)
- **Alertas:** Slack (log completo), Telegram (solo alta severidad / on-call)
- **Ataque/validación:** Atomic Red Team, dataset Mordor, dataset BOTS
- **CI/CD:** GitHub Actions (evals automáticos)

## Estado actual
- Diseño de arquitectura cerrado (3 fases, ver docs/arquitectura.md si se agrega detalle).
- 8 técnicas MITRE ATT&CK mapeadas: T1059.001, T1136.001, T1110.001, T1562.001,
  T1046, T1021.002, T1041, T1070.001.
- Harness de evaluación diseñado: `run_evaluation.py` dispara tests de Atomic Red Team
  vía WinRM, consulta Elastic Security por rule UUID + ventana temporal, consulta
  TheHive por veredicto del agente (custom fields), registra resultados en CSV.
  Dataset de 50 casos ya validado (TP variantes, FP legítimos, casos borderline).
- **Fase 1 (homelab SOC) completa y verificada — 2026-07-29.** `docker compose up -d`
  levanta los 9 servicios de forma estable:

  | Servicio | Estado | Acceso |
  |---|---|---|
  | Elasticsearch | healthy | localhost:9200 |
  | Kibana | up | localhost:5601 |
  | Wazuh Manager | up | API :55000 |
  | Filebeat (wazuh→ES) | up, enviando alertas | — |
  | Velociraptor | up | GUI https://localhost:8889 |
  | Cassandra | healthy | — |
  | TheHive | up, sin reinicios | localhost:9000 |
  | Redis | up | — |
  | n8n | up | localhost:5678 |

  Verificado end-to-end: las alertas de Wazuh llegan a Elasticsearch (índice `wazuh-alerts-*`).

  **3 bugs no obvios corregidos** (ya persistidos en `docker-compose.yml` y
  `filebeat/filebeat.yml`):
  1. **Velociraptor** — el binario no está en PATH ni tiene `+x` en la imagen
     `wlambert/velociraptor`. Se cambió el `entrypoint`/`command` para copiarlo
     a `/tmp`, darle permisos y ejecutarlo explícitamente; además se corrigió
     el bind de GUI/API a `0.0.0.0` (si no, el port-mapping de Docker no llega).
  2. **Filebeat** — generaba un índice tipo *data stream* mal configurado, y
     el 100% de las alertas de Wazuh se descartaban (HTTP 400). Se recreó como
     índice clásico (`setup.template.enabled: false`, `setup.ilm.enabled: false`)
     en `filebeat/filebeat.yml`.
  3. **TheHive** — crash-loop infinito (28 reinicios) por el flag `--s3-endpoint ""`,
     que activaba storage S3 sin credenciales. Se quitó del `command` en
     `docker-compose.yml`; ahora usa el volumen local (`thehive-data`) sin problema.

- **Fase 2 (agente de triage) — verificada end-to-end (2026-07-29).**
  `POST /triage` funciona de punta a punta: alerta → loop de tool-calling
  nativo de Ollama (`qwen3`) → invoca tools reales (`check_ioc_reputation`,
  `query_elastic_alerts`, `lookup_mitre_technique`) → `TriageVerdict` validado.
  Probado 2 veces con alerta sintética de brute-force SSH (IP de rango de
  documentación RFC 5737) → ambas con veredicto coherente (`FALSE_POSITIVE`).

  **Bug real corregido:** `src/agent/agent.py` usaba `ollama.Client()`
  (síncrono) dentro de un handler `async def`, bloqueando el event loop de
  Uvicorn durante cada inferencia (~5-10 min) — el propio `/health` fallaba
  mientras tanto. Cambiado a `ollama.AsyncClient()` + `await`. Verificado con
  34 chequeos de `/health` en paralelo durante una request completa: siempre
  `200 OK`. Imagen reconstruida y contenedor recreado con el fix aplicado.

  **Limitante de performance real:** `qwen3` en CPU corre a ~1.7-2 tok/seg y
  es un modelo "thinking" (razona en cadena antes de responder) → cada triage
  tarda 5-10 min. Usable para demo/portfolio, no para uso en tiempo real. Si
  se necesita más velocidad: evaluar un modelo más chico o correr con GPU.

  **Entorno:** el host (16GB RAM / 8 cores) quedó muy justo corriendo los 12
  servicios + inferencia LLM a la vez — Docker Desktop se cayó una vez bajo
  esa carga. Se subió el límite de WSL2 de ~8GB a 12GB vía
  `C:\Users\dario\.wslconfig` (`memory=12GB`, `processors=6`, `swap=4GB`),
  lo que estabilizó todo. Cambio persistente para próximas sesiones.

  Detalle de arquitectura (sin cambios de diseño, ya no "pendiente de correr"):
  - Nuevo paquete `src/agent/` (FastAPI) + 3 servicios en el mismo
    `docker-compose.yml`: `ollama`, `chroma` (puerto host 8010, no 8000, para
    no chocar con Velociraptor), `agent`.
  - `data/mitre_techniques.json`: 8 técnicas mapeadas, con
    `note: "TODO: completar con el rule UUID real"` — todavía sin completar.
  - `data/ioc_blocklist.json`: placeholder vacío, sin API externa todavía.
  - `tests/test_health.py`: pasa localmente.
  - **Sin probar esta sesión:** la tool `query_knowledge_base` / ChromaDB —
    ninguno de los 2 triages de prueba la invocó, `scripts/seed_kb.py` sigue
    sin correrse contra una instancia real.

- **Workflow n8n → TheHive/Slack/Telegram — importado y probado contra una
  instancia real de n8n (2.32.5), inactivo.** `n8n/workflows/wazuh-triage-to-thehive.json`
  (18 nodos, ver `n8n/README.md` para el detalle): cron cada 15 min → busca
  alertas nuevas en Elastic (ventana `now-16m`, `size: 5`) → Limit
  (`maxItems: 5`) → Loop Over Items (`batchSize: 1`, procesa 1 alerta a la
  vez) → dedup por Redis (TTL 24h) → arma el payload → `POST agent/triage`
  (timeout 40 min, por la latencia de `qwen3` — ver bug abajo) → mapea severidad a escala
  TheHive (1-4) → crea alerta en TheHive (`POST /api/v1/alert`, `sourceRef`
  = id de Wazuh) → Slack siempre → Telegram solo si `high`/`critical`; todos
  los caminos de salida vuelven al Loop Over Items para pedir el siguiente
  item. Secretos (`THEHIVE_API_KEY`, `SLACK_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID_ONCALL`) vía `$env.*` dentro de n8n, pasados desde
  `.env` al servicio `n8n` en `docker-compose.yml` — no están hardcodeados
  en el JSON del workflow.
  El cron a 15 min + el tope de 5 items/ejecución + el procesamiento
  secuencial son defensivos a propósito: la primera versión (cron cada 2 min,
  sin límite de items) casi apila decenas de llamadas al agente en una sola
  ejecución al probarla con una ventana ancha — se detectó y cortó a tiempo.
  Pendiente: no hay lock contra ejecuciones solapadas si 2+ alertas caen en
  el mismo ciclo de 15 min (poco probable en este homelab, pero sin resolver).

  **Credencial Redis (host `redis`, puerto `6379`, sin password) ya asignada
  en los 2 nodos Redis** del workflow reestructurado de 18 nodos — sin íconos
  de advertencia en el canvas.

  **Prueba end-to-end con alerta real — 2 rondas, 2 bugs distintos encontrados
  y corregidos (2026-07-30).**

  *Ronda 1:* alerta real generada apendeando al `dpkg.log` del contenedor
  Wazuh (no sintética). El agente terminó bien (2 vueltas de tool-calling,
  ~16 min), pero el timeout del nodo **Llamar agente /triage** (900000ms =
  15 min) cortó la conexión antes y n8n lo reportó como error falso.
  Corregido: timeout subido a 2400000ms (40 min) en
  `n8n/workflows/wazuh-triage-to-thehive.json`.

  *Ronda 2 (después de sincronizar el timeout con la instancia real):* el
  agente respondió `200 OK` en 12m44s — **confirmado, la conexión agente↔n8n
  con el timeout de 40 min ya no se corta.** Pero el siguiente nodo, **Crear
  alerta en TheHive**, falló con `access to env vars denied`: esta versión de
  n8n bloquea por default el acceso a `$env.*` dentro de expresiones de
  nodos, el patrón que usan los 3 nodos de salida (TheHive, Slack, Telegram)
  para leer secretos sin hardcodearlos en el JSON. Corregido: se agregó
  `N8N_BLOCK_ENV_ACCESS_IN_NODE: "false"` al servicio `n8n` en
  `docker-compose.yml` — falta recrear el contenedor (`docker compose up -d
  n8n`) para que tome el cambio, y reintentar.

  **Bug encontrado y corregido — casing de `severity` rompía el routing a
  Telegram (2026-07-31).** El agente (`qwen3:1.7b`) a veces devuelve
  `"severity":"HIGH"` en mayúsculas en vez de `"high"` — el nodo de n8n
  compara con `['high','critical'].includes($json.severity)` (case-sensitive)
  y el mapeo a escala TheHive también usa un objeto con claves en minúscula,
  así que con mayúsculas ambos fallan silenciosamente (cae a `medium`/no
  dispara Telegram) aunque el modelo haya clasificado bien. **Fix aplicado**
  en `src/agent/agent.py` (`triage_alert`): se normaliza `severity` a
  minúsculas y se valida contra el set válido (`low/medium/high/critical`,
  default `medium` si no matchea) antes de armar el `TriageVerdict`.
  Contenedor `agent` reconstruido (`docker compose build agent && docker
  compose up -d agent`) con el fix.

  **Slack cerrado, Telegram configurado pero sin confirmar aún (2026-07-31,
  mismo día que el fix de casing).** Se creó un bot de Telegram
  (`@aigis_detect1_bot`) y se completaron `TELEGRAM_BOT_TOKEN` y
  `TELEGRAM_CHAT_ID_ONCALL` en `.env` (chat privado del usuario). Para probar
  el nodo Telegram (solo dispara en `high`/`critical`, y las alertas
  dpkg.log salen `low`/`medium` por defecto) se usó la técnica de inyectar
  contenido de "incidente crítico" inequívoco (ransomware + C2 + movimiento
  lateral) en el `full_log` de una alerta dpkg real — funciona, en pruebas
  directas al agente (`POST /triage` sin pasar por n8n) se consiguió
  `severity: high` de esta forma. **Sesión cortada antes de confirmar el
  tramo completo:** al reintentar el workflow vía n8n con una alerta así, el
  nodo `Llamar agente /triage` devolvió `500 Internal Server Error` (no
  "connection aborted" como las veces anteriores — esta vez sí llegó
  respuesta, pero de error). La RAM del host estuvo rondando 90-120MB libres
  toda la prueba (mismo estrés ya documentado, pero sin llegar a un corte de
  conexión esta vez). **No se confirmó la causa raíz del 500** — el handler
  en `src/agent/main.py` captura toda excepción y la devuelve como
  `HTTPException(500, detail=str(exc))`, así que no queda traceback en
  `docker logs`, y el intento de reproducir la llamada directo (`POST
  /triage` con el mismo payload) quedó corriendo sin terminar cuando se
  cortó la sesión — no se llegó a ver el `detail` del error.

  **Para la próxima sesión:** repetir la llamada directa a `POST /triage`
  con contenido de severidad alta (ver ejemplo de "CRITICAL INCIDENT
  ransomware" arriba) y leer el body de la respuesta 500 completo (no solo
  el log de docker, que no tiene el traceback) para identificar la causa.
  Sospechas a revisar primero: (a) timeout interno del cliente de Ollama
  bajo memoria ajustada — la request tardó bastante más que los ~2 min
  típicos antes de fallar; (b) algo específico del contenido más largo/con
  más entidades (IP, nombres de archivo) que rompe el parseo JSON de la
  respuesta del modelo o el loop de tool-calling. Una vez resuelto, repetir
  el ciclo completo (alerta fresca → n8n → TheHive `high`/`critical` →
  Telegram) para cerrar el pendiente.

  Nota aparte: al momento de la ronda 2, TheHive estaba parado a propósito
  (para otra prueba), así que aunque se resuelva el bloqueo de `$env.*`, el
  nodo va a seguir fallando hasta levantar TheHive de nuevo. Y siguen sin
  completarse las env vars reales (`THEHIVE_API_KEY`, `SLACK_WEBHOOK_URL`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID_ONCALL` en `.env` — hoy vacías por
  default).

  **Ronda 3 (2026-07-31) — end-to-end CERRADO, agente → TheHive confirmado.**
  Al retomar la sesión, Docker Desktop estaba apagado del todo; al levantarlo
  los 10 servicios activos volvieron solos, pero `kibana` y `velociraptor`
  quedaron abajo (se habían parado a propósito la sesión anterior y no tienen
  restart automático — no afecta el pipeline de triage). Se encontró que
  `THEHIVE_API_KEY` en `.env` **ya tenía un valor real y válido** (cuenta de
  servicio `aigis-agent@aigis.local`, perfil `analyst`, permiso
  `manageAlert/create` confirmado contra `GET /api/v1/user/current`) y que
  `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` ya estaba aplicado en el contenedor
  `aigis-n8n` — los dos blockers de la ronda 2 ya estaban resueltos de una
  sesión anterior sin que quedara actualizado acá.

  Al reintentar con una alerta fresca (técnica dpkg.log), el nodo **Llamar
  agente /triage** volvió a cortarse con "the connection was aborted" — mismo
  patrón de fondo que antes, pero esta vez sin margen para el fix habitual de
  "parar Kibana/Velociraptor/TheHive" (Kibana y Velociraptor ya estaban
  abajo, y TheHive es justo el destino que se estaba probando). Diagnóstico:
  `wsl -e free -h` mostró 91MB libres de 11GB y swap en uso — el host tiene
  **16GB de RAM totales** y WSL2 ya tenía asignados 12GB (`.wslconfig`), sin
  margen seguro para subir más sin arriesgar la estabilidad de Windows mismo.
  Con los 10 servicios + `qwen3` (5.9GB) simultáneos no entra.

  **Fix aplicado — cambio de modelo a `qwen3:1.7b`:** se agregó
  `OLLAMA_MODEL=qwen3:1.7b` a `.env` (el compose ya soportaba la variable,
  default `qwen3`), se hizo `docker exec aigis-ollama ollama pull qwen3:1.7b`
  (1.4GB vs 5.2GB de `qwen3:latest`), se descargó el modelo viejo de memoria
  con `ollama stop qwen3:latest`, y se recreó el contenedor `agent`
  (`docker compose up -d agent`) para tomar la env var nueva. Resultado:
  RAM libre en WSL2 pasó de ~100MB a **5.6GB**. Prueba directa a `POST
  /triage` (sin pasar por n8n): respuesta `200 OK` en **~2 minutos** (vs
  5-15 min con `qwen3` grande), veredicto `BORDERLINE` coherente pero **sin
  invocar ninguna tool** (antes sí usaba `check_ioc_reputation`/
  `query_elastic_alerts`) — trade-off de calidad esperable con un modelo más
  chico, a tener en cuenta si el harness de evals después muestra falsos
  negativos por falta de tool-calling.

  Con el modelo chico, se generó una alerta fresca nueva (`aigis-retomar3-*`,
  `_id` Elasticsearch `m8WMtZ8BnOSnnydZ1Q8-`) y se re-ejecutó el workflow
  completo desde la UI de n8n. **Confirmado de punta a punta:** Redis dedup
  marcó la alerta → agente recibió `POST /triage` → `qwen3:1.7b` infirió →
  **se creó la alerta en TheHive** (`~4184`, "New dpkg (Debian Package)
  installed. — TRUE_POSITIVE", `sourceRef` = id de Wazuh, severity MEDIUM,
  tags `verdict:TRUE_POSITIVE` + `mitre:T1059.001`). El nodo **Slack - log
  completo** falló después con "URL parameter cannot be empty" — esperado,
  `SLACK_WEBHOOK_URL` sigue sin configurar (no es un bug nuevo). El tramo
  agente→TheHive, que era el único punto sin cerrar, queda validado.

  **Slack cerrado (2026-07-31, mismo día).** Dario generó un Incoming Webhook
  real en un app de Slack propio y lo pasó; se agregó `SLACK_WEBHOOK_URL` a
  `.env`, se recreó `aigis-n8n` (`docker compose up -d n8n`) y se probó el
  webhook directo con `curl` (200 OK) antes de gastar un ciclo completo de
  triage. Con una alerta fresca nueva se reintentó el workflow completo:
  Redis dedup → agente (`qwen3:1.7b`) → **TheHive** (`~12400`,
  "New dpkg... — FALSE_POSITIVE") → **Slack confirmado por el usuario en el
  canal real.** El tramo Slack del workflow queda cerrado. Telegram
  (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID_ONCALL`) sigue sin configurar —
  es el único canal de salida que falta, y solo dispara en `high`/`critical`
  así que es más difícil de probar con alertas sintéticas de severidad baja.

  **Nota de infra:** contenedor `ragapicloud-api-1` (no relacionado a este
  proyecto) está exited hace 6 días y reserva el puerto 8000 — mismo puerto
  que usa Velociraptor. No choca mientras siga caído, pero si algún día se
  levanta, va a chocar con el mapeo de puertos de Velociraptor en
  `docker-compose.yml`.

  **Ronda 4 (2026-07-31) — causa raíz del 500 de Telegram encontrada y
  corregida; bug nuevo y más profundo encontrado en el propio workflow de
  n8n, parcialmente cerrado.**

  *Causa raíz del 500 (el pendiente #1 de la ronda anterior):* no era RAM ni
  timeout — con contenido de severidad alta, `qwen3:1.7b` a veces devuelve
  `mitre_technique` como **lista** (ej.
  `["T1059.001 - Command and...", "...Clear Windows Event Logs"]`) en vez de
  string, lo que rompía la validación de Pydantic de `TriageVerdict`
  (`mitre_technique: Optional[str]`) y `main.py` lo reportaba como
  `500 Internal Server Error` sin traceback en logs (excepción genérica
  capturada y devuelta como `detail`). **Fix aplicado** en
  `src/agent/agent.py` (`triage_alert`): si `mitre_technique` es lista, se
  normaliza a string uniendo los valores con coma — mismo patrón defensivo
  que el fix de `severity` en mayúsculas de la ronda anterior. Contenedor
  `agent` reconstruido y recreado. Confirmado con `POST /triage` directo
  (payload de "CRITICAL INCIDENT ransomware"): `200 OK` en vez de 500.

  *Bug nuevo encontrado — el workflow de n8n nunca disparaba Telegram, para
  ninguna severidad, por pérdida de datos entre nodos HTTP encadenados.*
  El flujo real es `Mapear severidad TheHive → Crear alerta en TheHive →
  Slack - log completo → Es alta severidad? → Telegram - alta severidad`.
  Cada nodo `httpRequest` de n8n **reemplaza `$json` por su propia
  respuesta** por default — así que para cuando la ejecución llega al nodo
  IF, `$json` ya es la respuesta de Slack (que devuelve texto plano `"ok"`,
  representado por n8n como `{"data":"ok"}`), no los datos del agente. El
  IF evaluaba `{{$json.is_high_severity}}` sobre ese objeto, siempre
  `undefined` → siempre rama `false`, sin importar la severidad real. Esto
  además rompía (probablemente desde siempre) el **contenido** del mensaje
  de Slack, que referenciaba `$json.verdict`/`rule_description`/etc. sobre
  la respuesta de creación de alerta de TheHive (que no tiene esos campos)
  — la confirmación de Slack de la ronda anterior solo verificó que
  "llegó un mensaje", no que el contenido fuera correcto.

  **Fix aplicado** en `n8n/workflows/wazuh-triage-to-thehive.json`: los 3
  nodos (`Slack - log completo`, `Es alta severidad?`, `Telegram - alta
  severidad`) ahora referencian explícitamente
  `$('Mapear severidad TheHive').item.json.*` en vez de `$json.*`, mismo
  patrón que ya usaban otros nodos del workflow. Como n8n guarda el
  workflow en su propia base de datos (no lee el archivo en vivo), Dario
  aplicó el fix a mano en los 3 campos vía la UI y guardó — confirmado sin
  errores de expresión visibles en el canvas. (Nota aparte: al pegar los
  snippets, el archivo local `.json` quedó con saltos de línea reales en
  vez de `\n` escapado dentro de los strings — JSON inválido en disco,
  aunque el workflow real en n8n no tuvo el problema. Corregido en el
  archivo para que vuelva a ser JSON válido.)

  *Verificación end-to-end tras el fix, parcial:* se inyectó una segunda
  alerta crítica sintética (`telegram-verify2-ransomware-c2-*` en
  `dpkg.log`), confirmada en Elasticsearch, y Dario ejecutó el workflow
  manualmente. Resultado: **TheHive recibió la alerta correctamente**
  (`~40968312`, severity HIGH, `mitre_technique` con múltiples técnicas ya
  como string gracias al fix del agente — sin el bug de la ronda 3). El
  nodo IF mostró la rama `true` con 1 item (verde) yendo a Telegram, y el
  nodo Telegram mostró el mismo check verde que el resto — **pero el
  mensaje no llegó al chat real**, y al revisar el panel Input/Output del
  nodo Telegram en el canvas, ambos aparecían con **0 items** — contradice
  lo que mostraba la línea de conexión. Se descartó que sea un problema de
  credenciales: un `POST` directo a la API de Telegram con el mismo
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID_ONCALL` del `.env` **sí llegó** al
  chat de Dario al instante.

  **Hipótesis de trabajo, sin confirmar:** el canvas de n8n puede mostrar
  vistas cacheadas de ejecuciones distintas por nodo (cada nodo recuerda su
  "última corrida" individual, que no necesariamente coincide con la misma
  ejecución completa si hubo varios clicks de "Execute Workflow" en la
  sesión) — el 0 items visto en Telegram podría ser de una corrida vieja,
  no de la que generó `~40968312`. **Sesión cortada antes de confirmar**:
  el paso pendiente es abrir el historial real de "Executions" en n8n (no
  el canvas en vivo del editor) y revisar el registro inmutable de la
  ejecución específica que creó `~40968312`, nodo por nodo, para saber si
  Telegram realmente no recibió el item en esa corrida o si fue un
  artefacto de la vista del canvas.

## Decisiones clave
- Elasticsearch como único storage; Kibana como única capa de visualización.
- n8n como SOAR (aprovecha familiaridad previa de Dario).
- Slack = auditoría completa; Telegram = solo alta severidad.
- Deduplicación de alertas vía Redis con TTL corto.
- Diferenciador vs. proyectos públicos similares (soctalk, AI_SOC): harness de
  evaluación riguroso (tiempo de triage y precisión con/sin agente IA), no solo features.
- Reutilizar infra existente (Obsidian + Ollama + ChromaDB + LangChain + n8n),
  no reconstruir desde cero.
- Cada fase debe ser un artefacto de portfolio standalone (por si se acaba el tiempo).

## Próximos pasos
1. ~~Telegram~~ — **CERRADO (2026-08-01), confirmado por Dario en el chat real.**
   Causa raíz real (más profunda que el bug de referencias `$json` de la
   Ronda 4): esta versión de n8n (2.32.5) no ejecuta `workflow_entity.nodes`
   directamente, sino la versión apuntada por `activeVersionId`/
   `workflow_history` (versionado draft/publish). El fix de expresiones
   (`$('Mapear severidad TheHive').item.json.*`) se había guardado en
   `nodes` pero nunca se publicó como versión activa, así que el Schedule
   Trigger seguía corriendo el snapshot viejo (pre-fix) sin importar qué
   mostrara el canvas. Tras corregir `activeVersionId` (nueva fila en
   `workflow_history` + sync de `workflow_published_version`), la ejecución
   48 (tick 20:00 UTC, alerta `aigis-verify4-ransomware-c2-*`) confirmó los
   3 canales de salida (TheHive/Slack/Telegram) funcionando de punta a
   punta. El workflow quedó **activo** (antes era manual/disparo desde la
   UI) — Schedule Trigger corriendo cada 15 min de verdad. Detalle técnico
   completo en memoria (`aigis_detect_proximos_pasos.md`).
2. ~~Completar los `rule UUID` reales en `data/mitre_techniques.json`~~ —
   **CERRADO (2026-08-02).** Se levantó `aigis-wazuh-manager` standalone y se
   grepeó el ruleset por defecto de Wazuh 4.7.5 (`/var/ossec/ruleset/rules/`)
   buscando cada técnica MITRE. 7 de las 8 técnicas tienen `wazuh_rule_id`
   real documentado (ej. T1059.001 → rule 91823, T1110.001 → rules 5760/5763
   compuesta por frecuencia). Excepción: **T1041 (Exfiltration Over C2
   Channel) no tiene regla nativa aplicable** — la única coincidencia en el
   ruleset por defecto es específica de AWS Security Lake, no sirve para un
   homelab on-prem; requiere regla custom en `local_rules.xml`, sigue
   pendiente si se quiere cobertura real de esa técnica.
3. Workflow de GitHub Actions para correr los evals en CI.
4. ~~ChromaDB / `query_knowledge_base`~~ — **CERRADO (2026-08-01).**
   `scripts/seed_kb.py` nunca se había corrido; se corrió desde el host y
   cargó las 8 técnicas de `data/mitre_techniques.json` en la colección
   `aigis_kb` (confirmado con `collection.count()` = 8 + query semántica
   directa). Dos triages reales de prueba: uno (alerta con IOC/C2 explícito)
   no invocó la KB, el otro (alerta ambigua de SSH brute-force) sí invocó
   las 4 tools disponibles incluida `query_knowledge_base`. Tool confirmada
   funcionando end-to-end — el modelo decide caso a caso si la usa, mismo
   trade-off ya conocido de `qwen3:1.7b`.
5. ~~Correr el harness de evals con `qwen3:1.7b`~~ — **CERRADO (2026-08-02),
   resultado preocupante, no solo "regular".** Harness reducido de 12 casos
   (`scripts/run_evaluation.py`, ver docstring — bypassea Wazuh/n8n, llama
   `POST /triage` directo) contra el agente real:
   - **Veredicto correcto: 6/12 (50%). Técnica MITRE correcta: 2/10 (20%).
     Latencia promedio: 126s. 6/12 casos sin ninguna tool invocada.**
   - El patrón no es error al azar: de los 6 casos `TRUE_POSITIVE` reales,
     acertó 1 solo (`tp-05-borrado-event-log`) y **degradó los otros 5 a
     `FALSE_POSITIVE`/`BORDERLINE`** (PowerShell C2, SSH bruteforce externo,
     cuenta local sospechosa, Defender deshabilitado, exfiltración a dominio
     nuevo). Los 6 casos `FALSE_POSITIVE`/`BORDERLINE` reales los clasificó
     bien (6/6). **Sesgo sistemático a subestimar amenazas reales — el peor
     tipo de error para una herramienta de SOC (falsos negativos).**
     Resultados: `data/processed/eval_results_20260802-122436.csv`.
   - **Se probó `qwen3:4b` como punto medio y no es viable en este host:**
     los 12 casos fallaron con timeout (harness a 300s/caso). Logs de Ollama
     confirman que no es un bug — el modelo genera >900 tokens a ~2.8 tok/s
     sin terminar, muy por encima del timeout. RAM llegó a 97MB libres en
     WSL2 (sin thrashing/crash, solo cómputo lento en CPU). Se revirtió
     `.env` a `OLLAMA_MODEL=qwen3:1.7b`.
   - **Decisión:** se acepta `qwen3:1.7b` (50%/126s) como el punto
     latencia/precisión del proyecto para demo/portfolio, con la limitación
     documentada explícitamente acá y en el README. Si se necesita mejorar
     precisión real: forzar tool-calling obligatorio en el prompt del agente
     (en vez de dejarlo a discreción del modelo) es la vía más barata sin
     cambiar de modelo; `qwen3` grande (5-10 min/caso) queda como opción solo
     para casos puntuales, no para uso continuo ni para este harness.
6. (Opcional, baja prioridad) lock por Redis contra ejecuciones de n8n
   solapadas — documentado en `n8n/README.md`, no implementado; riesgo bajo
   con el cron a 15 min y tope de 5 items/ejecución.
7. ~~Fase 3: Terraform + AWS + honeypot expuesto a internet.~~ — **CERRADO
   (2026-08-03), pipeline honeypot→S3→homelab→Elasticsearch confirmado
   end-to-end.** Módulo completo en `infra/aws-honeypot/` (plan aprobado
   previamente en sesión de planning, ver README del módulo para arquitectura
   y decisiones de seguridad/costo). `terraform apply` corrido contra la
   cuenta AWS real (`aigis_dev`, cuenta 100747849204, región us-east-1).

   **5 bugs no obvios encontrados y corregidos durante el apply/verificación**
   (ya persistidos en `infra/aws-honeypot/main.tf` y `user_data.sh`):
   1. **`aws_security_group` description con caracteres no-ASCII** (em-dash,
      tildes) — AWS rechaza `GroupDescription` con `InvalidParameterValue:
      Character sets beyond ASCII are not supported`. Cambiado a texto plano
      en inglés.
   2. **Puerto 22 ocupado por el `sshd` real de la AMI** — la imagen base de
      EC2 trae `sshd` escuchando en :22 por default, y compite con el bind
      de Cowrie (`docker run -p 22:2222` fallaba con `address already in
      use`). Coherente con el diseño ("el 22 es 100% cebo, admin por SSM"):
      se agregó `systemctl disable --now sshd` a `user_data.sh` antes de
      levantar el contenedor.
   3. **`jsonlog` de Cowrie fallaba con `PermissionError`** — la imagen
      `cowrie/cowrie` corre como usuario no-root dentro del contenedor, y el
      bind mount del host (creado por `root` vía `mkdir`) no le daba permiso
      de escritura; Cowrie arrancaba pero sin loggear nada a
      `cowrie.json` (silencioso, solo visible en `docker logs`). Fix:
      `chmod 777` al directorio del host antes del `docker run`.
   4. **Filtro de AMI `al2023-ami-*-x86_64` matcheaba la variante
      ECS-optimized** (trae un `ecs-agent` que arranca solo y compite por
      recursos) — se descubrió al ver un contenedor `ecs-agent` corriendo
      sin haberlo pedido. Cambiado a la fuente canónica: `data
      "aws_ssm_parameter"` sobre
      `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`
      (recomendación oficial de AWS para no depender de filtros de nombre
      ambiguos).
   5. **Rol IAM del EC2 solo tenía `s3:PutObject`** — `aws s3 sync` (usado
      por el cron que sube los logs) también necesita `s3:ListBucket` para
      saber qué objetos ya existen; sin eso fallaba con `AccessDenied` en
      `ListObjectsV2`. Agregado `s3:ListBucket` scoped por `s3:prefix`
      (`cowrie/*`) a la policy del rol.

   Bugs 1-3 se parchearon primero en caliente vía SSM Run Command sobre la
   instancia ya viva (iteración rápida sin recrear nada); bug 4 obligó a un
   `terraform apply` con reemplazo de instancia (cambio de AMI) para partir
   de un estado limpio sin el `ecs-agent` fantasma — ahí sí corrió
   `user_data.sh` completo de punta a punta con los 3 fixes ya incluidos,
   sin intervención manual. Bug 5 es un cambio de IAM policy, sin impacto en
   la instancia.

   **Verificación end-to-end confirmada:** conexión SSH externa real →
   Cowrie la loggea en `cowrie.json` (formato JSON, incluye una conexión
   real ajena desde `186.109.67.48`, no generada por esta sesión — confirma
   que ya hay scanners de internet tocando la instancia) → cron cada 1 min
   sube el archivo a `s3://aigis-honeypot-logs-<account-id>/cowrie/` (rol
   IAM del EC2, sin credenciales estáticas) → `scripts/pull_honeypot_logs.py`
   (servicio `honeypot-puller` del compose, credenciales del IAM user
   "puller" de solo lectura) lo baja a `data/raw/cowrie/` → Filebeat (input
   nuevo en `filebeat/filebeat.yml`, sin tocar el input de Wazuh existente)
   lo manda a Elasticsearch, índice `cowrie-alerts-*`.

   Acceso admin verificado vía **SSM Run Command** (no se probó
   `ssm start-session` interactivo en esta sesión, pero el rol/agente están
   confirmados operativos — mismo mecanismo). Instancia activa:
   `i-022b9a65b44231310`, IP pública dinámica (sin Elastic IP a propósito,
   ver README del módulo). **Sigue corriendo y facturando** (bajo, dentro de
   free tier) — recordar `terraform destroy` en `infra/aws-honeypot/` cuando
   no se esté usando activamente para portfolio/demo.

   Alcance actual: standalone, no integrado al pipeline de triage IA/n8n
   (los ataques reales del honeypot no generan alertas en TheHive/Slack/
   Telegram todavía) — decisión de scope tomada en el planning original,
   sigue vigente.
8. TryHackMe SOC Level 1 en paralelo, para alimentar casos de prueba reales al agente.

9. **Escalación Tier 2 (`agent-orchestrator-soc`) — agregada por otra sesión
   (16 de agosto de 2026, commits `0e7ed02`/`4a866ad`/`a5f958d`/`2a104cb`) y
   re-verificada e investigada el 17 de agosto de 2026. CERRADO, sin bug
   real encontrado.** Cuando `aigis-agent` clasifica una alerta como
   `high`/`critical`, un nodo nuevo en el workflow de n8n
   (`n8n/workflows/wazuh-triage-to-thehive.json`) hace POST a
   `agent-orchestrator-soc` (repo hermano del portfolio, standalone en
   `~/Proyectos/03-Ciberseguridad-BlueTeam/agent-orchestrator-soc`,
   `host.docker.internal:5679/webhook/soc-alert`, `continueOnFail: true`
   para no romper el pipeline principal si Tier 2 está caído). Ese
   proyecto corre su propio pipeline LangGraph supervisor-worker
   (enrichment → research → report) y expone `POST /triage` +
   `POST /triage/{thread_id}/approve` para la decisión humana final.

   **Investigación (17 de agosto):** el historial de ejecuciones de
   `aigis-n8n` mostraba la única corrida que había llegado a ese nodo
   (ejecución #288, 16 de agosto) marcada como `crashed`
   (`NodeCrashedError`, "n8n may have run out of memory") — parecía una
   falla real del puente Tier1→Tier2. Se descartó: el reporte generado por
   esa corrida (`reports/ZuNzC6ABe-S8l_KoWY-N.md` en el repo de
   `agent-orchestrator-soc`) es real y su timestamp coincide exactamente —
   `aigis-n8n` murió por el crash-loop de diagnósticos (el mismo que
   corrigió el commit `0e7ed02` deshabilitando
   `N8N_DIAGNOSTICS_ENABLED`/`N8N_VERSION_NOTIFICATIONS_ENABLED`/
   `N8N_TEMPLATES_ENABLED`) *mientras esperaba* la respuesta lenta de
   Tier 2, después de que el receptor ya había procesado la request por
   completo. No hay bug de payload/formato en el nodo emisor — se verificó
   simulando la expresión JS del nodo con datos reales (produce JSON
   válido) y con dos corridas en vivo.

   Con el fix del crash-loop ya aplicado (traído por `git pull` el mismo
   día), se repitió la prueba de punta a punta con una alerta sintética
   nueva, disparada únicamente por el cron de 15 min sin intervención
   manual: verdict `TRUE_POSITIVE`/`HIGH` (T1059.001) → Telegram entregado
   de verdad (`message_id: 12`, chat real de Dario) → nodo de escalación
   exitoso en 85s (sin crash) → `status: pending_approval` con enrichment y
   research reales → `reports/1j5EEKAB9-YbN60pVYPK.md` generado en disco.
   Segunda confirmación independiente de la cadena completa. Docs en
   `docs/threat-model-purple-team-demo.md` (afirmación original de
   `a5f958d`) confirmados como correctos — no hicieron falta correcciones,
   solo un addendum (`2f0cc8b`) con este hallazgo.

   Las "Failed to parse request body" vistas en los logs de
   `soc-orchestrator-n8n` (la instancia n8n del otro repo) no se
   correlacionan con ninguna de las dos corridas exitosas investigadas —
   esa instancia tiene su propio historial de crashes ("Last session
   crashed") separado. Queda fuera del alcance de este repo; no se tocó
   `agent-orchestrator-soc` más allá de levantar su stack para la prueba y
   leer (no modificar) `tools.py`/`api.py`/los workflows de n8n.

   **Pendiente de limpieza manual, no es un incidente sin resolver:** el
   reporte `reports/1j5EEKAB9-YbN60pVYPK.md` (repo `agent-orchestrator-soc`)
   quedó en `status: pending_approval` a propósito — viene de la alerta
   sintética de la verificación de arriba, no de un evento real, y
   aprobarlo lo metería en el historial como si fuera un hallazgo real
   confirmado (rompe el principio de evidencia verificable del proyecto).
   El endpoint `/triage/{thread_id}/approve` solo acepta
   `decision: "approved"|"rejected"` — no hay una forma de etiquetar
   "test sintético, sin acción" sin marcarlo como una decisión real, así
   que se dejó tal cual sin llamar ese endpoint. Si se quiere limpiar,
   hacerlo a mano (aprobar/rechazar sabiendo que es sintético, o borrar el
   estado directamente) — no requiere ninguna acción sobre `aigis-detect`.

   Stack `soc-orchestrator-n8n`/`-app`/`-ollama` se levantó solo para esta
   prueba y se bajó al terminar (`docker compose down` en el repo de
   `agent-orchestrator-soc`) — no queda corriendo entre sesiones.

## Notas de entorno
- WSL2 configurado con `memory=12GB`, `processors=6`, `swap=4GB` en
  `C:\Users\dario\.wslconfig` — necesario para correr los 12 servicios +
  inferencia LLM sin que Docker Desktop se caiga.
- **Host con 16GB de RAM totales — WSL2 en 12GB ya es el máximo seguro**, no
  hay margen para subirlo más sin arriesgar la estabilidad de Windows. Con
  los 10 servicios activos + `qwen3` (5.9GB) el sistema entra en *thrashing*
  de swap y corta conexiones TCP entre contenedores (ver Ronda 3). Por eso el
  agente corre con **`OLLAMA_MODEL=qwen3:1.7b`** (1.4GB) en vez de `qwen3`
  grande — deja ~5.6GB libres y responde en ~2 min en vez de 5-15 min, al
  costo de un triage algo menos exhaustivo (no siempre invoca tools). Si se
  necesita volver al modelo grande para algún caso puntual, bajar
  Kibana/Velociraptor/TheHive antes de disparar el triage.
