"""
Cache Manager for OpenContracts.

Implements multi-tier caching strategy:
- L1: Django's cache (in-memory, request-scoped)
- L2: Redis (shared across instances)
- L3: Materialized views (database)

This significantly reduces database load and improves response times.
"""

import redis
import json
import hashlib
import logging
from typing import Any, Optional, Callable, Dict
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

class CacheManager:
    """
    Centralized cache management for OpenContracts.

    Usage:
        from opencontractserver.utils.cache_manager import cache_manager

        # Get or compute with caching
        result = cache_manager.get_or_set(
            key="my_key",
            callable=expensive_function,
            ttl=300
        )
    """

    def __init__(self):
        """Initialize Redis connection."""
        self.redis_client = redis.Redis(
            host=getattr(settings, 'REDIS_HOST', 'localhost'),
            port=getattr(settings, 'REDIS_PORT', 6379),
            db=getattr(settings, 'REDIS_DB', 0),
            decode_responses=True
        )
        self.enabled = getattr(settings, 'CACHE_ENABLED', True)

    def cache_key(self, prefix: str, **kwargs) -> str:
        """
        Generate consistent cache key from parameters.

        Args:
            prefix: Key prefix (e.g., "manifest", "page_annotations")
            **kwargs: Parameters to include in key

        Returns:
            Cache key string

        Example:
            key = cache_key("manifest", doc=123, corpus=456)
            # Returns: "manifest:a1b2c3d4"
        """
        # Sort kwargs for consistent key generation
        key_data = json.dumps(kwargs, sort_keys=True)
        key_hash = hashlib.md5(key_data.encode()).hexdigest()[:8]
        return f"oc:{prefix}:{key_hash}"

    def get_or_set(
        self,
        key: str,
        callable: Callable,
        ttl: int = 300,
        cache_null: bool = False,
        use_l1: bool = True,
        use_l2: bool = True
    ) -> Any:
        """
        Get value from cache or compute and cache it.

        Args:
            key: Cache key
            callable: Function to compute value if not cached
            ttl: Time to live in seconds (default: 5 minutes)
            cache_null: Whether to cache null results
            use_l1: Whether to use Django cache
            use_l2: Whether to use Redis cache

        Returns:
            Cached or computed value

        Performance:
            - L1 hit: <1ms
            - L2 hit: 1-5ms
            - Cache miss: Depends on callable
        """
        if not self.enabled:
            return callable()

        # Try L1 cache (Django)
        if use_l1:
            result = cache.get(key)
            if result is not None:
                logger.debug(f"L1 cache hit: {key}")
                return result

        # Try L2 cache (Redis)
        if use_l2:
            try:
                redis_result = self.redis_client.get(key)
                if redis_result:
                    result = json.loads(redis_result)
                    logger.debug(f"L2 cache hit: {key}")

                    # Warm L1 cache
                    if use_l1:
                        cache.set(key, result, 60)

                    return result
            except redis.RedisError as e:
                logger.warning(f"Redis error for key {key}: {e}")

        # Compute result
        logger.debug(f"Cache miss: {key}, computing...")
        result = callable()

        # Cache if not null (or if caching nulls)
        if result is not None or cache_null:
            # Set in L1 cache
            if use_l1:
                cache.set(key, result, min(60, ttl))

            # Set in L2 cache
            if use_l2:
                try:
                    self.redis_client.setex(
                        key,
                        ttl,
                        json.dumps(result, default=str)
                    )
                except redis.RedisError as e:
                    logger.warning(f"Failed to set Redis cache for {key}: {e}")

        return result

    def invalidate(self, key: str):
        """Invalidate specific cache key."""
        cache.delete(key)
        try:
            self.redis_client.delete(key)
        except redis.RedisError:
            pass

    def invalidate_pattern(self, pattern: str):
        """
        Invalidate all keys matching pattern.

        Args:
            pattern: Redis pattern (e.g., "oc:manifest:*")
        """
        try:
            # Clear from Redis
            for key in self.redis_client.scan_iter(match=pattern):
                self.redis_client.delete(key)

            # Clear from Django cache (limited pattern support)
            cache.delete_many(cache.keys(pattern))
        except redis.RedisError as e:
            logger.warning(f"Failed to invalidate pattern {pattern}: {e}")

    def get_annotation_manifest(
        self,
        document_id: int,
        corpus_id: int,
        analysis_id: Optional[int] = None
    ) -> Optional[Dict]:
        """
        Get cached annotation manifest for a document.

        This is the primary method for getting document annotation statistics
        and navigation data without loading all annotations.

        Args:
            document_id: Document ID
            corpus_id: Corpus ID
            analysis_id: Analysis ID (optional)

        Returns:
            Annotation manifest dictionary or None

        Performance:
            - Cached: 1-5ms
            - Uncached: 50-100ms (uses materialized view)
        """
        key = self.cache_key(
            "manifest",
            doc=document_id,
            corpus=corpus_id,
            analysis=analysis_id
        )

        def compute():
            from opencontractserver.utils.query_optimizer import QueryOptimizer
            return QueryOptimizer.get_document_annotation_stats(
                document_id,
                corpus_id
            )

        return self.get_or_set(key, compute, ttl=300)

# Global cache manager instance
cache_manager = CacheManager()

# Cache warming utilities
def warm_document_cache(document_id: int, corpus_id: int):
    """
    Pre-warm caches for a document.
    Called after document upload or major changes.
    """
    from opencontractserver.utils.query_optimizer import QueryOptimizer

    # Warm manifest cache
    cache_manager.get_annotation_manifest(document_id, corpus_id)

    # Warm first few pages
    for page in range(1, 6):
        key = cache_manager.cache_key(
            "page_annotations",
            doc=document_id,
            corpus=corpus_id,
            page=page
        )

        annotations = QueryOptimizer.batch_load_annotations_by_page(
            document_id,
            [page],
            corpus_id
        )

        cache_manager.get_or_set(
            key,
            lambda: annotations,
            ttl=600
        )