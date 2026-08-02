"""Loop de triage: function calling nativo de Ollama sobre las 4 tools del
proyecto (MITRE lookup, query a Elastic, reputación de IOC, KB semántica).

Se usa function calling nativo en vez de LangChain a propósito — regla de ROI
del proyecto: sumar una capa extra solo si el nativo se queda corto.
"""
import json

import ollama

from .config import MAX_TOOL_ITERATIONS, OLLAMA_HOST, OLLAMA_MODEL
from .schemas import AlertInput, TriageVerdict
from .tools import elastic, ioc, mitre
from .tools import knowledge_base as kb

_client = ollama.AsyncClient(host=OLLAMA_HOST)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_mitre_technique",
            "description": (
                "Devuelve metadata de una técnica MITRE ATT&CK mapeada en el "
                "proyecto (nombre, táctica, notas de detección)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "technique_id": {"type": "string", "description": "Ej: T1059.001"},
                },
                "required": ["technique_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_elastic_alerts",
            "description": (
                "Busca alertas recientes en Elasticsearch (índice wazuh-alerts-*), "
                "opcionalmente filtradas por rule_id, para ver contexto/frecuencia."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                    "size": {"type": "integer", "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_ioc_reputation",
            "description": "Chequea si un IP/dominio/hash está en la blocklist conocida.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "ioc_type": {"type": "string", "enum": ["ip", "domain", "hash"]},
                },
                "required": ["value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_base",
            "description": "Busca en runbooks y notas de detección propias por similitud semántica.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
]

_SYNC_TOOL_IMPL = {
    "lookup_mitre_technique": lambda args: mitre.lookup_technique(args["technique_id"]),
    "check_ioc_reputation": lambda args: ioc.check_ioc(args["value"], args.get("ioc_type", "ip")),
    "query_knowledge_base": lambda args: kb.query_kb(args["question"]),
}

SYSTEM_PROMPT = """Sos un analista de triage de un SOC. Recibís una alerta de Wazuh/Elastic
y tenés que decidir si es TRUE_POSITIVE, FALSE_POSITIVE o BORDERLINE, asignar severidad
(low/medium/high/critical), identificar la técnica MITRE ATT&CK si aplica, y sugerir una
acción concreta. Usá las herramientas disponibles para investigar antes de responder.
Respondé SIEMPRE en JSON con las claves: verdict, severity, mitre_technique, explanation,
suggested_action. No inventes datos que las herramientas no confirmaron."""


async def triage_alert(alert: AlertInput) -> TriageVerdict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(alert.model_dump(), ensure_ascii=False)},
    ]
    tool_calls_made: list[str] = []
    msg: dict = {}

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await _client.chat(model=OLLAMA_MODEL, messages=messages, tools=TOOLS)
        msg = response["message"]
        messages.append(msg)

        calls = msg.get("tool_calls")
        if not calls:
            break

        for call in calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            tool_calls_made.append(name)

            if name == "query_elastic_alerts":
                result = await elastic.query_alerts(args.get("rule_id"), size=args.get("size", 20))
            elif name in _SYNC_TOOL_IMPL:
                result = _SYNC_TOOL_IMPL[name](args)
            else:
                result = {"error": f"tool desconocida: {name}"}

            messages.append({
                "role": "tool",
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

    try:
        parsed = json.loads(msg.get("content", ""))
    except json.JSONDecodeError:
        parsed = {
            "verdict": "borderline",
            "severity": "medium",
            "mitre_technique": None,
            "explanation": f"El modelo no devolvió JSON válido: {msg.get('content', '')[:300]}",
            "suggested_action": "Revisión manual — falló el parseo de la respuesta del agente.",
        }

    severity = str(parsed.get("severity", "medium")).lower()
    if severity not in ("low", "medium", "high", "critical"):
        severity = "medium"

    mitre_technique = parsed.get("mitre_technique")
    if isinstance(mitre_technique, list):
        mitre_technique = ", ".join(str(t) for t in mitre_technique) or None

    return TriageVerdict(
        alert_id=alert.alert_id,
        verdict=parsed.get("verdict", "borderline"),
        severity=severity,
        mitre_technique=mitre_technique,
        explanation=parsed.get("explanation", ""),
        suggested_action=parsed.get("suggested_action", ""),
        tool_calls=tool_calls_made,
    )
