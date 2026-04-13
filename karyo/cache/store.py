from __future__ import annotations

import hashlib
import os
from typing import Any, Optional

import diskcache


class CacheStore:
    """Thread-safe diskcache wrapper with CACHE_ONLY guard."""

    def __init__(self) -> None:
        cache_dir = os.getenv("KARYO_CACHE_DIR", "./cache")
        self._cache = diskcache.Cache(cache_dir)
        self._cache_only = os.getenv("KARYO_CACHE_ONLY", "0") == "1"

    @staticmethod
    def make_key(*args: Any) -> str:
        """Hash arbitrary arguments into a stable cache key."""
        key_str = str(args)
        return hashlib.sha256(key_str.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        value = self._cache.get(key)
        if value is None and self._cache_only:
            raise RuntimeError(f"Cache miss in CACHE_ONLY mode: {key}")
        return value

    def set(self, key: str, value: Any) -> None:
        self._cache.set(key, value)

    def close(self) -> None:
        self._cache.close()


# Module-level singleton
_store: Optional[CacheStore] = None


def get_store() -> CacheStore:
    global _store
    if _store is None:
        _store = CacheStore()
    return _store
