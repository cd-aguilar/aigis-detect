"""Reputación de IOCs.

Placeholder offline: chequea contra data/ioc_blocklist.json (lista local, sin
API externa todavía). Cuando se sume una key de VirusTotal/AbuseIPDB en .env,
reemplazar check_ioc() por una llamada real y mantener esta firma de salida.
"""
import json

from ..config import IOC_BLOCKLIST_PATH

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(IOC_BLOCKLIST_PATH, encoding="utf-8") as f:
                _cache = json.load(f)
        except FileNotFoundError:
            _cache = {"ips": [], "domains": [], "hashes": []}
    return _cache


def check_ioc(value: str, ioc_type: str = "ip") -> dict:
    """Chequea un IP/dominio/hash contra la blocklist local."""
    data = _load()
    known_bad = value in data.get(f"{ioc_type}s", [])
    return {
        "value": value,
        "type": ioc_type,
        "known_bad": known_bad,
        "source": "blocklist local (placeholder — sin API externa aún)",
    }
