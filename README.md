# aigis-detect

SOC Lab Portfolio — homelab local con SIEM (Elastic Stack + Wazuh Manager),
SOAR (n8n + TheHive), DFIR (Velociraptor) y un agente de triage con IA
(Ollama + ChromaDB + FastAPI). Fase 1 y Fase 2 verificadas end-to-end;
falta conectar el agente al flujo SOAR (workflow n8n, ver abajo) y probarlo
contra un n8n real. Base para el despliegue en AWS (Fase 3).

## Arquitectura Fase 1

- **Elasticsearch + Kibana**: único storage y visualización.
- **Wazuh Manager** sin su indexer nativo (OpenSearch) — las alertas se leen
  de `alerts.json` y se envían a Elasticsearch vía **Filebeat**.
- **TheHive + Cassandra**: gestión de casos, indexa sobre el mismo Elasticsearch.
- **n8n**: orquestación de playbooks (SOAR) y alerting (Slack log completo,
  Telegram solo alta severidad — se configura como credenciales dentro de n8n).
- **Velociraptor**: DFIR / respuesta a incidentes.
- **Redis**: deduplicación de alertas con TTL corto.

## Primer arranque

1. `cp .env.example .env` (PowerShell: `Copy-Item .env.example .env`) y completar
   secretos (`THEHIVE_SECRET`, `N8N_PASSWORD`, etc).
2. Generar el config de Velociraptor (una sola vez, antes del primer `up` —
   usa el volumen ya definido en el compose, funciona igual en bash y PowerShell):
   ```
   docker compose run --rm --entrypoint velociraptor velociraptor config generate -c /velociraptor/server.config.yaml
   ```
3. `docker compose up -d`
4. Ver estado de los contenedores: `docker compose ps` (todos deberían quedar
   `running`/`healthy` en 1-3 min; Elasticsearch y Cassandra tardan más en arrancar).
5. Verificar salud:
   - Kibana: http://localhost:5601
   - TheHive: http://localhost:9000
   - n8n: http://localhost:5678
   - Velociraptor GUI: https://localhost:8889
6. Confirmar que las alertas de Wazuh llegan a Elasticsearch:
   `curl http://localhost:9200/wazuh-alerts-*/_search?size=1`
7. Logs si algo no levanta: `docker compose logs -f <servicio>`
   (ej. `docker compose logs -f wazuh-manager`).

## Requisitos

Docker Compose v2, ~16 GB RAM / 4 vCPU recomendados (ES + Cassandra + Wazuh +
TheHive corriendo juntos). Para laptops con menos RAM, bajar `ES_JAVA_OPTS`
y `MAX_HEAP_SIZE` en `docker-compose.yml`, o comentar TheHive/Cassandra si
no se necesita gestión de casos en esa sesión de trabajo.

## Fase 2 — agente de triage con IA

Servicios nuevos en el mismo `docker-compose.yml`: `ollama`, `chroma`, `agent`
(FastAPI, se construye desde el `Dockerfile` de la raíz). Código en `src/agent/`.

1. Levantar los servicios nuevos (con Fase 1 ya arriba, o solo, si no necesitás
   el resto ahora):
   ```
   docker compose up -d ollama chroma agent
   ```
2. Descargar el modelo (una sola vez):
   ```
   docker compose exec ollama ollama pull qwen3
   ```
3. Cargar la base de conocimiento en ChromaDB (corre desde el host, no en Docker):
   ```
   pip install chromadb --break-system-packages
   python scripts/seed_kb.py
   ```
4. Probar el endpoint:
   ```
   curl -X POST http://localhost:8080/triage \
     -H "Content-Type: application/json" \
     -d '{"alert_id": "test-1", "rule_id": "100002", "rule_description": "PowerShell execution detected"}'
   ```
5. Health check simple: `curl http://localhost:8080/health`

**Estado de `data/mitre_techniques.json`:** 7 de las 8 técnicas ya tienen su
`wazuh_rule_id` real (extraído del ruleset de Wazuh 4.7.5). Excepción:
T1041 (Exfiltration Over C2 Channel) no tiene regla nativa aplicable en un
homelab on-prem — requiere una regla custom en `local_rules.xml`.

**Nota de performance:** `qwen3` corriendo en CPU tarda 5-10 min por triage
(modelo "thinking", ~1.7-2 tok/seg). Sirve para demo/portfolio; para uso en
tiempo real habría que evaluar un modelo más chico o correr con GPU.

## Workflow SOAR (n8n → TheHive/Slack/Telegram)

`n8n/workflows/wazuh-triage-to-thehive.json` conecta todo lo anterior:
alerta nueva en Elastic → agente → alerta en TheHive con el veredicto →
Slack (siempre) → Telegram (solo alta/crítica). Pasos de import, credencial
de Redis y variables de entorno necesarias en `n8n/README.md`.

## Próximos pasos

Ver `CLAUDE.md` — correr el harness de evals (`run_evaluation.py`) con
`qwen3:1.7b`, workflow de GitHub Actions para evals, y Fase 3
(Terraform + AWS) son los siguientes entregables.
