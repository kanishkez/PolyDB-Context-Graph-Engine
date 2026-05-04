"""Service wrapper for embedding operations."""
from typing import Dict, List, Tuple

from embeddings.faiss_store import embedding_store


class EmbeddingService:

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        return embedding_store.search(query, top_k=top_k)

    def upsert_table_embedding(self, node_id: str, table_data: Dict):
        embedding_store.upsert(node_id, table_data)

    def batch_upsert(self, items: List[Tuple[str, Dict]]):
        embedding_store.batch_upsert(items)

    def save(self):
        embedding_store.save()

    def load(self):
        embedding_store.load()

    @property
    def total_vectors(self) -> int:
        return embedding_store.total_vectors


embedding_service = EmbeddingService()
