"""Servicio FastAPI del agente de triage — Aigis-Detect, Fase 2."""
from fastapi import FastAPI, HTTPException

from .agent import triage_alert
from .schemas import AlertInput, TriageVerdict

app = FastAPI(title="Aigis-Detect Triage Agent", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/triage", response_model=TriageVerdict)
async def triage(alert: AlertInput):
    try:
        return await triage_alert(alert)
    except Exception as exc:  # noqa: BLE001 — se reporta al caller, no se traga
        raise HTTPException(status_code=500, detail=str(exc)) from exc
