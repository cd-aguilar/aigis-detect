# Aigis-Detect · Fase 2 — Agente de triage (FastAPI)
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/agent ./agent
COPY data/mitre_techniques.json ./data/mitre_techniques.json
COPY data/ioc_blocklist.json ./data/ioc_blocklist.json

ENV PYTHONUNBUFFERED=1 \
    MITRE_TECHNIQUES_PATH=/app/data/mitre_techniques.json \
    IOC_BLOCKLIST_PATH=/app/data/ioc_blocklist.json

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8080"]
