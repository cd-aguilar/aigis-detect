"""Configuración del agente, vía variables de entorno (ver .env.example)."""
import os

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3")

ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
ALERTS_INDEX = os.getenv("ALERTS_INDEX", "wazuh-alerts-*")

CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "aigis_kb")

MITRE_TECHNIQUES_PATH = os.getenv("MITRE_TECHNIQUES_PATH", "/app/data/mitre_techniques.json")
IOC_BLOCKLIST_PATH = os.getenv("IOC_BLOCKLIST_PATH", "/app/data/ioc_blocklist.json")

MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "4"))
