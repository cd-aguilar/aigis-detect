"""Contrato de entrada/salida del agente de triage."""
from typing import Any, Optional

from pydantic import BaseModel, Field


class AlertInput(BaseModel):
    alert_id: str
    rule_id: Optional[str] = None
    rule_description: Optional[str] = None
    timestamp: Optional[str] = None
    agent_name: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class TriageVerdict(BaseModel):
    alert_id: str
    verdict: str  # "true_positive" | "false_positive" | "borderline"
    severity: str  # "low" | "medium" | "high" | "critical"
    mitre_technique: Optional[str] = None
    explanation: str
    suggested_action: str
    tool_calls: list[str] = Field(default_factory=list)
