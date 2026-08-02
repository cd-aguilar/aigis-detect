"""Lookup de técnicas MITRE ATT&CK mapeadas en este proyecto (data/mitre_techniques.json)."""
import json

from ..config import MITRE_TECHNIQUES_PATH

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        with open(MITRE_TECHNIQUES_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def lookup_technique(technique_id: str) -> dict:
    """Devuelve metadata de una técnica MITRE ATT&CK mapeada en el proyecto."""
    techniques = _load()
    return techniques.get(
        technique_id,
        {
            "technique_id": technique_id,
            "name": "desconocida",
            "note": "Técnica no mapeada en este proyecto todavía.",
        },
    )
