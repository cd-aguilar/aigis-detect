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
                  [Tier 2: agent-orchestrator-soc — nodo agregado hoy]
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
  (`reports/wazuh-92099-001.md`) — incluye identificación de T1059.001 y
  T1027, usuario `FINANCE\jgomez`, recomendación de Script Block Logging.
  Esto prueba que el endpoint de decisión humana (`/triage/{id}/approve`,
  workflow "SOC Triage Approve") también está operativo.

**3. Hallazgo honesto sobre no-determinismo del modelo.**
El mismo tipo de alerta (T1059.001, PowerShell ofuscado + C2) fue evaluado
dos veces hoy de forma independiente — una vez vía el pipeline automático
completo, otra vez manualmente contra `aigis-agent` directo — y **ambas
veces el modelo clasificó BORDERLINE/MEDIUM, no TRUE_POSITIVE/HIGH**. Esto
es coherente con el run de evaluación del harness (ver métricas abajo,
`tp-01-powershell-c2` también salió MISS en la corrida del 2 de agosto). Es
una limitación real y documentada del modelo actual (qwen3), no un defecto
del pipeline: la infraestructura de detección→triage→escalación funciona
correctamente: el problema es que el clasificador no siempre es lo
suficientemente sensible para este caso puntual. Para el demo grabado, se
recomienda usar un caso con clasificación HIGH más consistente (ver
checklist abajo) o mostrar explícitamente esta inconsistencia como parte
del análisis honesto de límites del sistema.

**4. Nodo de escalación (Tier 2) — validado por componentes, no aún en un
run automático que haya cruzado ambos tiers de punta a punta en una sola
ejecución.** El bridge en sí (ítem 2) y el Tier 1 automático (ítem 1) están
cada uno probados con evidencia real e independiente. Lo que falta para
cerrar el círculo es una ejecución automática donde la MISMA alerta salga
HIGH de Tier 1 y dispare Tier 2 sin intervención manual — no ocurrió hoy
porque el caso de prueba usado clasificó MEDIUM (ítem 3), no por una falla
del nodo. Es el primer paso pendiente antes de grabar (ver checklist).

## Métricas reales del harness de evaluación (Tier 1)

Fuente: `data/processed/eval_results_20260802-122436.csv` — 12 casos
(6 TRUE_POSITIVE, 3 FALSE_POSITIVE, 3 BORDERLINE), corrida completa sin
interrupciones. **No se usan los resultados de la corrida de hoy**: se
interrumpió a mitad de camino porque coincidió con un reinicio de
contenedores hecho para depurar el bridge, y 8 de 12 casos dieron timeout
de infraestructura (no error del modelo) — habría sido deshonesto citarlos
como medición de precisión.

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
- **El scheduler de n8n mostró fragilidad durante iteración rápida en vivo**
  (reimportar/reactivar el workflow varias veces en pocos minutos, o bajar
  el intervalo a 20s, lo dejó sin disparar en un par de ocasiones sin que
  el contenedor crasheara). Con el intervalo de producción (15 min) y sin
  tocar el workflow mientras corre, el historial de hoy mismo muestra
  ejecuciones exitosas ininterrumpidas por más de 4 horas (12:00–16:00).
  Recomendación: no reimportar/reactivar el workflow mientras se prepara la
  grabación; si hace falta un cambio, hacerlo una sola vez y dejarlo
  correr sin tocarlo al menos 20–30 min antes de confiar en el cron.

## Qué prueba este demo (y qué no)
**Prueba:** que una alerta real de Wazuh puede recorrer automáticamente el
pipeline de Tier 1 hasta crear un caso en TheHive sin intervención humana,
que existe un puente funcional y ya ejercitado hacia una investigación
Tier 2 más profunda con gate de aprobación humana, y que hay métricas
reales (no estimadas) de cuán bien clasifica el modelo actual.

**No prueba (todavía):** una ejecución automática de punta a punta donde la
MISMA alerta cruce Tier 1 → Tier 2 → decisión sin ningún paso manual, ni
eficacia frente a ataques reales no vistos en producción.

## Checklist antes de grabar
1. Dejar el stack completo corriendo sin tocarlo 20–30 min para confirmar
   que el cron de 15 min sigue estable (ya en curso al momento de escribir
   esto).
2. Buscar o construir un caso que el agente clasifique de forma consistente
   como HIGH/CRITICAL (candidatos: variar el prompt del caso ransomware
   usado hoy, o correr el mismo caso varias veces y quedarse con una
   corrida real que escale — sin descartar las que no escalan, mostrarlas
   como parte del análisis de límites si se quiere).
3. Una vez que un caso HIGH dispare Tier 2 automáticamente sin intervención,
   capturar ese log/ejecución como la prueba definitiva de punta a punta.
4. Grabar: alerta sintética → Wazuh/Elastic → TheHive (Tier 1) → Tier 2
   (si escala) → decisión vía `/approve` → reporte final.
5. Acompañar el video con este documento y las métricas del harness como
   evidencia de que "aigis-detect" no es una demo de juguete sino un
   sistema con evaluación honesta.
