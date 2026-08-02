"""Query semántica a la base de conocimiento (ChromaDB) — runbooks y notas de
detección propias. Se carga con scripts/seed_kb.py.
"""
import chromadb

from ..config import CHROMA_COLLECTION, CHROMA_HOST, CHROMA_PORT

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return _client


def query_kb(question: str, n_results: int = 3) -> list[dict]:
    """Busca en la base de conocimiento por similitud semántica."""
    client = _get_client()
    collection = client.get_or_create_collection(CHROMA_COLLECTION)
    results = collection.query(query_texts=[question], n_results=n_results)
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    return [{"text": d, "metadata": m} for d, m in zip(docs, metas)]
