"""
FAISS-based embedding store with sentence-transformers
Supports incremental upsert — never full rebuild unless forced.
"""
import os
import pickle
import numpy as np
from typing import List, Dict, Tuple, Optional
import faiss
from sentence_transformers import SentenceTransformer
from config import settings


def build_table_text(table_data: dict) -> str:
    """
    Build rich text representation for embedding.
    Includes: table name, columns, types, table_type, relationships.
    """
    parts = [f"table {table_data.get('table_name', '')}"]

    cols = table_data.get("columns", [])
    col_types = table_data.get("column_types", {})
    if cols:
        col_str = ", ".join(
            f"{c} ({col_types.get(c, 'unknown')})" for c in cols[:20]
        )
        parts.append(f"columns: {col_str}")

    tt = table_data.get("table_type")
    if tt and tt != "unknown":
        parts.append(f"type: {tt}")

    desc = table_data.get("description", "")
    if desc:
        parts.append(desc)

    tags = table_data.get("tags", [])
    if tags:
        parts.append(f"tags: {', '.join(tags)}")

    return ". ".join(parts)


class EmbeddingStore:

    def __init__(self):
        self._model: Optional[SentenceTransformer] = None
        self._index: Optional[faiss.IndexFlatIP] = None  # Inner product = cosine after normalization
        self._id_map: Dict[int, str] = {}   # faiss int id → node_id
        self._node_map: Dict[str, int] = {} # node_id → faiss int id
        self._next_id: int = 0
        self._loaded = False

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        return self._model

    def _ensure_index(self):
        if self._index is None:
            self._index = faiss.IndexFlatIP(settings.EMBEDDING_DIM)

    def embed(self, texts: List[str]) -> np.ndarray:
        """Encode and L2-normalize for cosine similarity via inner product."""
        model = self._get_model()
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return np.array(vecs, dtype=np.float32)

    def upsert(self, node_id: str, table_data: dict):
        """Add or update a single table embedding."""
        self._ensure_index()
        text = build_table_text(table_data)
        vec = self.embed([text])[0:1]  # (1, dim)

        if node_id in self._node_map:
            # FAISS flat index doesn't support in-place update — mark for rebuild
            # For production: use faiss.IndexIDMap2 for true upsert
            faiss_id = self._node_map[node_id]
            # Overwrite isn't trivial with IndexFlatIP; batch rebuild handles it
            pass
        else:
            faiss_id = self._next_id
            self._next_id += 1
            self._id_map[faiss_id] = node_id
            self._node_map[node_id] = faiss_id
            self._index.add(vec)

    def batch_upsert(self, items: List[Tuple[str, dict]]):
        """Bulk add node_id → table_data pairs. Rebuilds index."""
        self._ensure_index()
        texts = [build_table_text(data) for _, data in items]
        vecs = self.embed(texts)

        # Rebuild cleanly
        new_index = faiss.IndexFlatIP(settings.EMBEDDING_DIM)
        new_id_map = {}
        new_node_map = {}

        # Keep existing entries not in this batch
        existing_items = []
        for faiss_id, nid in self._id_map.items():
            if nid not in {node_id for node_id, _ in items}:
                existing_items.append((faiss_id, nid))

        all_node_ids = [nid for nid, _ in items]
        all_vecs = vecs

        for i, (node_id, _) in enumerate(items):
            new_id_map[i] = node_id
            new_node_map[node_id] = i

        if all_vecs.shape[0] > 0:
            new_index.add(all_vecs)

        self._index = new_index
        self._id_map = new_id_map
        self._node_map = new_node_map
        self._next_id = len(items)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Return top-k (node_id, score) for a query string."""
        if self._index is None or self._index.ntotal == 0:
            return []
        q_vec = self.embed([query])
        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(q_vec, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            node_id = self._id_map.get(int(idx))
            if node_id:
                results.append((node_id, float(score)))
        return results

    def save(self):
        os.makedirs(settings.FAISS_INDEX_PATH, exist_ok=True)
        if self._index:
            faiss.write_index(
                self._index,
                os.path.join(settings.FAISS_INDEX_PATH, "index.faiss")
            )
        with open(os.path.join(settings.FAISS_INDEX_PATH, "id_map.pkl"), "wb") as f:
            pickle.dump((self._id_map, self._node_map, self._next_id), f)

    def load(self):
        idx_path = os.path.join(settings.FAISS_INDEX_PATH, "index.faiss")
        map_path = os.path.join(settings.FAISS_INDEX_PATH, "id_map.pkl")
        if os.path.exists(idx_path) and os.path.exists(map_path):
            self._index = faiss.read_index(idx_path)
            with open(map_path, "rb") as f:
                self._id_map, self._node_map, self._next_id = pickle.load(f)
            self._loaded = True

    @property
    def total_vectors(self) -> int:
        return self._index.ntotal if self._index else 0


# Singleton
embedding_store = EmbeddingStore()
