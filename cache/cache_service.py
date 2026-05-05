"""
In-memory cache layer with TTL support.
Drop-in replaceable with Redis via same interface.
"""
import time
import hashlib
import json
from typing import Any, Optional
from collections import OrderedDict
from config import settings


class TTLCache:
    """LRU + TTL cache."""

    def __init__(self, max_size: int = 1000, ttl: int = 300):
        self._store: OrderedDict = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def _key(self, raw: str) -> str:
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        k = self._key(key)
        entry = self._store.get(k)
        if not entry:
            return None
        value, expires_at = entry
        if time.time() >= expires_at:
            del self._store[k]
            return None
        self._store.move_to_end(k)
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        k = self._key(key)
        ttl = self._ttl if ttl is None else ttl
        if k in self._store:
            self._store.move_to_end(k)
        self._store[k] = (value, time.time() + ttl)
        if len(self._store) > self._max_size:
            self._store.popitem(last=False)  # evict oldest

    def delete(self, key: str):
        k = self._key(key)
        self._store.pop(k, None)

    def clear(self):
        self._store.clear()

    def size(self) -> int:
        return len(self._store)


class CacheService:
    """
    Three separate caches:
    - query_cache: smart_query results
    - context_cache: table context expansions
    - embedding_cache: search results for queries
    """

    def __init__(self):
        self.query_cache = TTLCache(
            max_size=settings.QUERY_CACHE_SIZE,
            ttl=settings.CACHE_TTL_SECONDS
        )
        self.context_cache = TTLCache(
            max_size=500,
            ttl=settings.CACHE_TTL_SECONDS * 2
        )
        self.embedding_cache = TTLCache(
            max_size=2000,
            ttl=settings.CACHE_TTL_SECONDS
        )

    def cache_key(self, *args) -> str:
        return json.dumps(args, sort_keys=True, default=str)

    def get_query(self, query: str, user_id: Optional[str] = None) -> Optional[Any]:
        return self.query_cache.get(self.cache_key("query", query, user_id))

    def set_query(self, query: str, result: Any, user_id: Optional[str] = None):
        self.query_cache.set(self.cache_key("query", query, user_id), result)

    def get_context(self, table_id: str) -> Optional[Any]:
        return self.context_cache.get(f"ctx:{table_id}")

    def set_context(self, table_id: str, ctx: Any):
        self.context_cache.set(f"ctx:{table_id}", ctx)

    def get_search(self, query: str, top_k: int) -> Optional[Any]:
        return self.embedding_cache.get(self.cache_key("search", query, top_k))

    def set_search(self, query: str, top_k: int, results: Any):
        self.embedding_cache.set(self.cache_key("search", query, top_k), results)

    def invalidate_table(self, node_id: str):
        """Clear context cache when a table is updated."""
        self.context_cache.delete(f"ctx:{node_id}")

    def reset(self):
        """Clear all internal caches (useful for test isolation)."""
        self.query_cache.clear()
        self.context_cache.clear()
        self.embedding_cache.clear()


def create_cache_service() -> CacheService:
    """Factory for tests that need isolated cache instances."""
    return CacheService()


cache_service = CacheService()
