#!/usr/bin/env python3
"""Carga la base de conocimiento inicial en ChromaDB: las técnicas MITRE
mapeadas en el proyecto (data/mitre_techniques.json).

Correr desde el host (no dentro de Docker), con el compose ya levantado:
    pip install chromadb --break-system-packages
    python scripts/seed_kb.py

Usa el puerto de Chroma expuesto al host (8010 por default en docker-compose.yml).
"""
import json
import os
import sys

import chromadb

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT_HOST", "8010"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "aigis_kb")
TECHNIQUES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "mitre_techniques.json")


def main() -> int:
    with open(TECHNIQUES_PATH, encoding="utf-8") as f:
        techniques = json.load(f)

    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collection = client.get_or_create_collection(CHROMA_COLLECTION)

    ids, docs, metas = [], [], []
    for technique_id, info in techniques.items():
        ids.append(technique_id)
        docs.append(f"{technique_id} — {info['name']} ({info.get('tactic', '')}): {info.get('note', '')}")
        metas.append({"technique_id": technique_id, "tactic": info.get("tactic", "")})

    collection.upsert(ids=ids, documents=docs, metadatas=metas)
    print(f"Cargadas {len(ids)} técnicas en la colección '{CHROMA_COLLECTION}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
