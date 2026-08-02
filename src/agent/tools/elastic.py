"""Query de alertas en Elasticsearch (índice wazuh-alerts-*, ver Fase 1)."""
from typing import Optional

import httpx

from ..config import ALERTS_INDEX, ELASTICSEARCH_URL


async def query_alerts(rule_id: Optional[str] = None, size: int = 20) -> list[dict]:
    """Busca alertas recientes en Elasticsearch, opcionalmente filtradas por rule_id.

    Sirve para que el agente vea contexto/frecuencia antes de emitir un veredicto
    (ej. ¿esta regla dispara seguido en este host? ¿es la primera vez?).
    """
    query = {"match_all": {}} if not rule_id else {"match": {"rule.id": rule_id}}
    body = {"query": query, "size": size, "sort": [{"@timestamp": "desc"}]}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{ELASTICSEARCH_URL}/{ALERTS_INDEX}/_search", json=body)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        return [h["_source"] for h in hits]
