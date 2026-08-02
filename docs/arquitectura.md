# Arquitectura del pipeline — Aigis-Detect

De la alerta cruda que genera Wazuh a la notificación en Slack o Telegram,
pasando por un agente de IA con tool-calling que decide el veredicto — así
fluyen los datos hoy, servicio por servicio.

- **Fase 1** (homelab SOC) — completa.
- **Fase 2** (agente de triage) — verificado end-to-end.
- **Pipeline** TheHive + Slack + Telegram — confirmado 2026-08-01.

Versión visual (mismo diagrama, con tabla de servicios y estilo dark/light):
https://claude.ai/code/artifact/33dd78eb-08f1-4e55-b462-10e307aeaa79

## Flujo de datos

```mermaid
flowchart LR
    subgraph SIEM["1 · Ingesta & SIEM"]
        direction TB
        WM["Wazuh Manager<br/>:1514/udp agentes · :55000 API"]
        FB["Filebeat<br/>módulo wazuh → sin indexer nativo"]
        ES[("Elasticsearch<br/>wazuh-alerts-*")]
        KB["Kibana<br/>:5601"]
        WM -->|alerts.json| FB
        FB -->|bulk index| ES
        ES --> KB
    end

    subgraph ORQ["2 · Orquestación · n8n"]
        direction TB
        CRON{{"Schedule Trigger<br/>cron cada 15 min"}}
        LIM["Buscar + Limit<br/>now-16m · size 5"]
        LOOP["Loop Over Items<br/>1 alerta a la vez"]
        DEDUP{"Redis dedup<br/>TTL 24h"}
        CRON --> LIM --> LOOP --> DEDUP
    end

    subgraph IA["3 · Agente de triage IA"]
        direction TB
        AGENT["Agent · FastAPI<br/>:8080 · POST /triage"]
        OLLAMA["Ollama<br/>qwen3:1.7b"]
        TOOLS[["Tools: IOC rep · MITRE lookup<br/>query_elastic_alerts"]]
        CHROMA[("ChromaDB<br/>knowledge base — sin confirmar uso")]
        AGENT --> OLLAMA
        AGENT --> TOOLS
        AGENT -.-> CHROMA
    end

    subgraph CASE["4 · Case management & alerting"]
        direction TB
        MAP["Mapear severidad<br/>escala TheHive 1–4"]
        THEHIVE[("TheHive<br/>:9000 · crea alerta")]
        SLACK["Slack<br/>log completo, toda severidad"]
        IFHIGH{"severity<br/>high / critical?"}
        TELE["Telegram<br/>solo on-call"]
        MAP --> THEHIVE
        MAP --> SLACK
        MAP --> IFHIGH
        IFHIGH -->|sí| TELE
    end

    subgraph DFIR["DFIR · uso manual"]
        VELO["Velociraptor<br/>GUI :8889"]
    end

    ES -->|poll cada 15 min| CRON
    DEDUP -->|nueva| AGENT
    DEDUP -.->|duplicada, se descarta| LOOP
    AGENT -->|TriageVerdict json| MAP
    WM -.->|investigación puntual, no automatizado| VELO
```

## Servicios (docker-compose.yml)

| Servicio | Rol en el pipeline | Puerto host | |
|---|---|---|---|
| `wazuh-manager` | Recibe eventos de agentes y genera alertas (`alerts.json`) | 1514/udp · 1515 · 55000 | core |
| `filebeat` | Envía `alerts.json` del manager a Elasticsearch (módulo wazuh) | — | core |
| `elasticsearch` | Storage único — índice `wazuh-alerts-*` | 9200 | core |
| `kibana` | Visualización de alertas | 5601 | core |
| `n8n` | SOAR — cron 15 min, dedup, triage → TheHive/Slack/Telegram | 5678 | core |
| `redis` | Deduplicación de alertas (TTL 24h) | — | core |
| `agent` | FastAPI — triage con tool-calling nativo de Ollama | 8080 | core |
| `ollama` | Inferencia local — `qwen3:1.7b` | 11435 → 11434 | core |
| `chroma` | Knowledge base del agente (uso aún sin confirmar) | 8010 → 8000 | core |
| `thehive` + `cassandra` | Case management — recibe alertas triageadas | 9000 | core |
| `velociraptor` | DFIR — investigación manual, fuera del flujo automatizado | 8000 · 8889 · 8001 | manual |

---
*Generado a partir de `docker-compose.yml` + `n8n/workflows/wazuh-triage-to-thehive.json`.*
