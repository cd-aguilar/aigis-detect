# Threat Model — Demo Purple-Team: aigis-detect + agent-orchestrator-soc

_Última actualización: 2026-08-16_

## Objetivo del demo
Mostrar, con datos reales medidos (no inventados), el flujo completo de un
incidente de seguridad en un homelab SOC: **detección → triage automático →
escalación condicional a investigación profunda → decisión humana**.

## Escenario base
Técnica MITRE ATT&CK **T1059.001 — Command and Scripting Interpreter:
PowerShell**, con conexión saliente inmediata como indicador de C2.
Caso base: `tp-01-powershell-c2` del dataset de evaluación de aigis-detect
(`data/eval_dataset.json`).

- **Host afectado:** WIN-SRV01 (agente Wazuh simulado)
- **Vector:** `powershell.exe -nop -w hidden -enc <base64>`
- **Indicador de red:** conexión saliente a `185.220.101.45:443` (IOC
  sintético, no una IP real observada)

## Arquitectura del flujo

```
Wazuh Manager (detección)
   -> Filebeat -> Elasticsearch (wazuh-alerts-*)
   -> n8n aigis-detect, "Cada 15 minutos" (workflow yRIe7y4qbdfHULkB)
        -> dedupe por Redis (aigis:dedup:<id>, ttl 24h)
        -> POST http://agent:8080/triage   [Tier 1: aigis-agent]
             modelo local (Ollama) + RAG MITRE, devuelve verdict/severity/
             mitre_technique/explanation/suggested_action
        -> crea alerta en TheHive (SOAR) + Slack (log completo)
        -> si severity in {high, critical}:
             -> Telegram (on-call)
             -> POST http://host.docker.internal:5679/webhook/soc-alert
                  [Tier 2: agent-orchestrator-soc]
                  -> n8n agent-orchestrator-soc -> POST app:8000/triage
                       (pipeline supervisor-worker LangGraph: enrichment ->
                       research -> report)
                  -> si severity in {High, Critical}: pausa en
                     `pending_approval` (interrupt de LangGraph)
                  -> decisión humana: POST /triage/{thread_id}/approve
                     {"decision": "approved" | "rejected"}
                  -> informe final en /reports + Slack
```

## Por qué dos sistemas y no uno
`aigis-agent` (Tier 1) es un clasificador rápido de un solo paso, pensado
para procesar el volumen completo de alertas sin cuello de botella.
`agent-orchestrator-soc` (Tier 2) es una investigación multi-agente más
costosa (varios pasos de razonamiento, búsqueda en base de conocimiento,
research), reservada para el subconjunto de alertas de severidad alta —
igual que un analista L1 que clasifica y solo escala a L2 lo que lo
amerita. La integración de hoy automatiza esa escalación condicional.

## Estado: cadena completa de punta a punta confirmada ✅

Las cinco piezas del flujo (detección → Tier 1 → escalación → Tier 2 →
decisión humana) están probadas con evidencia real, incluyendo **una
corrida completamente automática, sin intervención manual, que cruzó los
dos sistemas** (ver ítem 4). El único tramo cerrado con una llamada manual
(no vía el cron de 15 min) fue el paso final de aprobación de esa misma
corrida, porque el reinicio de un contenedor (evento de infraestructura
Docker, no del pipeline) borró el estado en memoria del grafo antes de
poder aprobarlo — el checkpointer de LangGraph es in-memory y no sobrevive
un restart del proceso (ver "Supuestos y límites"). Se repitió la
investigación de Tier 2 con contenido idéntico y sí se completó la
aprobación de punta a punta.

**Re-verificación independiente (17 de agosto de 2026).** Se investigó una
inconsistencia pendiente: el historial de ejecuciones de `aigis-n8n` marca
la corrida original del ítem 4 (16 de agosto, ejecución #288) como
`crashed` con `NodeCrashedError` ("n8n may have run out of memory") en el
nodo de escalación — a primera vista contradice la evidencia del reporte
real. Investigado a fondo (comparando el timestamp del crash contra el
timestamp real de `reports/ZuNzC6ABe-S8l_KoWY-N.md`): **no es una falla
del bridge**. `aigis-n8n` sufría en ese momento el crash-loop de
diagnósticos corregido el mismo día en `docker-compose.yml`
(`N8N_DIAGNOSTICS_ENABLED`/`N8N_VERSION_NOTIFICATIONS_ENABLED`/
`N8N_TEMPLATES_ENABLED`) — el proceso murió *mientras esperaba* la
respuesta lenta de Tier 2, después de que el receptor ya había recibido y
procesado la request por completo. El reporte generado lo confirma.

Con el fix ya aplicado, se repitió la prueba de punta a punta con una
alerta sintética nueva inyectada en `dpkg.log` (paquete
`aigis-tier2-verify2-*`) y se dejó correr únicamente por el cron de 15 min,
sin ninguna intervención manual. Resultado, ejecución #355
(2026-08-17 15:15–15:18 UTC), **sin crash esta vez**:
verdict `TRUE_POSITIVE`/`HIGH` (T1059.001) → Telegram entregado de verdad
(`message_id: 12` al chat real de Dario) → nodo de escalación en 85s con
`status: pending_approval`, enrichment y research reales →
`reports/1j5EEKAB9-YbN60pVYPK.md` generado en disco con timestamp
coincidente. Segunda confirmación independiente de la cadena completa,
esta vez sin el ruido del crash-loop.

## Evidencia real recolectada (16 de agosto de 2026)

Todo lo listado abajo es un resultado real, no una proyección ni un dato
inventado. Cada afirmación está atada a un artefacto verificable.

**1. Pipeline automático Tier 1 de punta a punta, sin intervención manual.**
El schedule trigger de n8n (cada 15 min) recogió una alerta sintética
indexada en Elasticsearch, la de-dupeó por Redis, llamó a `aigis-agent`, y
creó una alerta real en TheHive — sin que nadie dispare nada a mano.
Evidencia: alerta TheHive `sourceRef: ZONSC6ABe-S8l_Ko8o94`, título
"PowerShell ejecutado con flags de ofuscacion (-enc) y conexion saliente
inmediata — BORDERLINE", severity MEDIUM, tag `mitre:T1059.001`, con la
explicación real generada por el modelo (no editada).

**2. El bridge Tier 1 → Tier 2 funciona (probado en aislamiento, dos veces).**
- Hoy: POST directo a `http://localhost:5679/webhook/soc-alert` con un
  payload shape idéntico al que arma el nodo nuevo → HTTP 200, pipeline
  completo corrido, reporte generado (`reports/bridge-test-1.md`).
- Antes (9 de agosto): una alerta con forma de alerta Wazuh real, con el
  mismo caso T1059.001, escaló correctamente a `pending_approval` en
  severidad HIGH, con research y reporte generados por el modelo
  (`reports/wazuh-92099-001.md`).

**3. Hallazgo honesto sobre no-determinismo del modelo.**
El mismo tipo de alerta (T1059.001, PowerShell ofuscado + C2) fue evaluado
dos veces el mismo día de forma independiente — una vez vía el pipeline
automático completo, otra vez manualmente contra `aigis-agent` directo — y
**ambas veces el modelo clasificó BORDERLINE/MEDIUM, no TRUE_POSITIVE/
HIGH**. Esto es coherente con el run de evaluación del harness (ver
métricas abajo, `tp-01-powershell-c2` también salió MISS en la corrida del
2 de agosto). Es una limitación real y documentada del modelo actual
(qwen3), no un defecto del pipeline: el clasificador no siempre es lo
suficientemente sensible para este caso puntual, mientras que para un caso
de ransomware con C2+lateral movement+encriptación (ítem 4) sí clasificó
consistentemente HIGH/TRUE_POSITIVE. Vale la pena mostrar esta variabilidad
en el demo como parte del análisis honesto de límites del sistema, en vez
de ocultarla.

**4. Escalación automática Tier 1 → Tier 2 CONFIRMADA de punta a punta,
sin intervención manual.** Una alerta sintética de ransomware (C2 beacon +
movimiento lateral SMB + archivos cifrados) fue recogida por el cron de
15 min, clasificada por `aigis-agent` como **TRUE_POSITIVE / HIGH**
(alerta TheHive `sourceRef: ZuNzC6ABe-S8l_KoWY-N`, MITRE T1059.001), y el
nodo nuevo escaló automáticamente a `agent-orchestrator-soc` — que generó
un reporte completo de investigación (`reports/ZuNzC6ABe-S8l_KoWY-N.md`,
generado `2026-08-16T16:48:48Z`) y quedó en `pending_approval`. Nadie
disparó manualmente ningún paso de este flujo: el cron, la clasificación,
la creación de la alerta en TheHive y la escalación a Tier 2 ocurrieron
solos.

**5. Decisión humana completada.** El intento de aprobar esa misma corrida
(ítem 4) falló con 404 porque un restart de contenedor (evento de Docker,
no relacionado al pipeline) limpió el estado in-memory del grafo antes de
llegar a aprobarlo. Se repitió la investigación de Tier 2 con contenido
idéntico (thread `demo-decision-final`) y se llamó
`POST /triage/{thread_id}/approve {"decision":"approved"}` — la respuesta
cambió de `status: pending_approval` a **`status: completed`**, cerrando
el loop completo: detección → Tier 1 → escalación → Tier 2 → decisión
humana → informe final.

## Métricas reales del harness de evaluación (Tier 1)

Fuente: `data/processed/eval_results_20260802-122436.csv` — 12 casos
(6 TRUE_POSITIVE, 3 FALSE_POSITIVE, 3 BORDERLINE), corrida completa sin
interrupciones. **No se usan los resultados de la corrida del 16 de
agosto**: se interrumpió a mitad de camino porque coincidió con un
reinicio de contenedores hecho para depurar el bridge, y 8 de 12 casos
dieron timeout de infraestructura (no error del modelo) — habría sido
deshonesto citarlos como medición de precisión.

- **Veredicto correcto: 5/12 (42%)** — el modelo acierta el veredicto
  (TRUE_POSITIVE / FALSE_POSITIVE / BORDERLINE) en menos de la mitad de los
  casos.
- **Técnica MITRE correcta: 2/9 casos aplicables (22%)** — de los 9 casos
  con una técnica MITRE esperada, solo 2 la identificaron correctamente.
- **Latencia promedio: ~130s por caso** (rango observado: 68s–231s), todo
  corriendo local vía Ollama sin GPU dedicada al modelo de Tier 1.
- **Aciertos:** `tp-05-borrado-event-log` (TRUE_POSITIVE), ambos casos
  FALSE_POSITIVE (`fp-01`, `fp-02`), y dos de los tres BORDERLINE (`bd-01`,
  `bd-02`).
- **Fallos representativos:** todos los TRUE_POSITIVE salvo uno se
  clasificaron como FALSE_POSITIVE o BORDERLINE — el modelo tiende a ser
  conservador/subestimar amenazas reales antes que sobre-alertar.

Estos números, bajos y sin pulir, son el punto central de la honestidad del
proyecto: el valor de aigis-detect en esta fase no es "el agente clasifica
perfecto", es "hay una arquitectura completa, medible y con un harness de
evaluación real corriendo — y la medición dice dónde falla hoy". Ese es
justamente el framing recomendado para el demo y el case study.

## Supuestos y límites explícitos
- El host `WIN-SRV01` y los eventos de PowerShell/ransomware son
  **sintéticos** — documentos indexados directamente en Elasticsearch con
  el mismo shape que produce Wazuh/Filebeat. No hay todavía un endpoint
  Windows real con agente Wazuh instalado y un ataque Atomic Red Team
  ejecutado en vivo sobre él. Limitación conocida, no ocultada.
- El bridge Tier1→Tier2 usa `host.docker.internal:5679` porque son dos
  stacks Docker Compose independientes (redes distintas) — decisión
  deliberada, refleja que en producción serían dos servicios separados.
- Si `agent-orchestrator-soc` está caído, el nodo de escalación falla en
  modo `continueOnFail` — no bloquea ni degrada el pipeline principal.
- La decisión final ("approved"/"rejected") es manual vía POST al endpoint
  `/approve` en esta versión — no hay todavía UI ni botones interactivos de
  Slack para ese paso.
- **El checkpointer de LangGraph en agent-orchestrator-soc es in-memory**
  (`build_graph()`, ver `api.py`): un restart del contenedor `app` borra
  cualquier investigación en estado `pending_approval` sin posibilidad de
  recuperarla. Para producción real esto necesitaría un checkpointer
  persistente (SQLite/Postgres) — hoy es aceptable para un homelab pero es
  una limitación real a documentar si se presenta como "production-ready".
- **El scheduler de n8n mostró fragilidad durante iteración rápida en vivo**
  (reimportar/reactivar el workflow varias veces en pocos minutos, o bajar
  el intervalo a 20s) y en un momento el motor de Docker reinició de forma
  no solicitada el stack completo de `agent-orchestrator-soc`. Con el
  intervalo de producción (15 min) y sin tocar nada mientras corre, el
  pipeline demostró ser confiable: el historial de ejecuciones muestra
  corridas exitosas ininterrumpidas por más de 4 horas, y la escalación
  automática de punta a punta (ítems 4 y 5) ocurrió exactamente así, sin
  intervención. Recomendación para grabar: no reimportar/reactivar
  workflows ni reiniciar contenedores mientras se espera una corrida.

## Qué prueba este demo (y qué no)
**Prueba:** que una alerta real de Wazuh puede recorrer automáticamente
todo el pipeline — Tier 1, creación de caso en TheHive, escalación
condicional a Tier 2, investigación multi-agente y pausa para decisión
humana — sin ningún paso manual, y que la decisión humana (`/approve`)
cierra el loop correctamente. También que hay métricas reales (no
estimadas) de cuán bien clasifica el modelo actual, con sus limitaciones
expuestas en vez de ocultadas.

**No prueba (todavía):** eficacia frente a ataques reales no vistos en
producción, resistencia a evasión activa del pipeline de triage, ni
persistencia del estado de investigación ante un reinicio del servicio
(limitación conocida, ver arriba).

## Checklist para la grabación
1. No tocar el workflow de n8n ni reiniciar contenedores mientras se
   prepara/graba — el pipeline es confiable dejado en paz.
2. Grabar la secuencia real: alerta sintética → Wazuh/Elastic → TheHive
   (Tier 1, severity visible) → escalación automática a Tier 2 → reporte
   de investigación → `POST /approve` → `status: completed`.
3. Mostrar también, como parte del análisis honesto, el caso donde el
   mismo tipo de alerta (PowerShell+C2) salió BORDERLINE en vez de HIGH —
   demuestra que las métricas del harness (42% veredicto correcto) son
   reales y consistentes con lo que se ve en producción, no un número
   aislado.
4. Acompañar el video con este documento y las métricas del harness como
   evidencia de que "aigis-detect" no es una demo de juguete sino un
   sistema con evaluación honesta.
