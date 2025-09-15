"""
Query optimizer for annotation queries.
Provides optimized querysets based on access patterns.
"""

import logging
from typing import Any, Optional

from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Max, Min, Prefetch, Q, QuerySet

logger = logging.getLogger(__name__)


class AnnotationQueryOptimizer:
    """
    Optimizer for annotation queries that intelligently chooses between
    direct queries and materialized views based on the query pattern.
    """

    # Thresholds for choosing query strategy
    USE_MV_THRESHOLD = 100  # Use materialized view if expecting > 100 annotations
    CACHE_TTL = 300  # Cache results for 5 minutes

    @classmethod
    def get_document_annotations(
        cls,
        document_id: int,
        corpus_id: Optional[int] = None,
        page: Optional[int] = None,
        structural: Optional[bool] = None,
        analysis_id: Optional[int] = None,
        use_cache: bool = True,
    ) -> QuerySet:
        """
        Get optimized queryset for document annotations.

        Args:
            document_id: Document ID
            corpus_id: Optional corpus ID filter
            page: Optional page number filter
            structural: Optional structural filter
            analysis_id: Optional analysis ID filter
            use_cache: Whether to use caching

        Returns:
            Optimized QuerySet
        """
        from opencontractserver.annotations.models import Annotation

        # Build cache key
        cache_key = f"doc_annotations:{document_id}:{corpus_id}:{page}:{structural}:{analysis_id}"

        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached

        # Start with base query
        qs = Annotation.objects.filter(document_id=document_id)

        # Apply filters
        if corpus_id is not None:
            qs = qs.filter(corpus_id=corpus_id)

        if page is not None:
            qs = qs.filter(page=page)

        if structural is not None:
            qs = qs.filter(structural=structural)

        if analysis_id is not None:
            if analysis_id == 0:  # User annotations (no analysis)
                qs = qs.filter(analysis_id__isnull=True)
            else:
                qs = qs.filter(analysis_id=analysis_id)

        # Choose optimization strategy based on filters
        if page is not None:
            # Page-specific queries benefit from indexes
            qs = qs.select_related("annotation_label", "creator")
            logger.debug(f"Using indexed page query for doc {document_id}, page {page}")

        elif structural is False and corpus_id is not None:
            # Non-structural corpus queries benefit from our composite index
            qs = qs.select_related("annotation_label", "creator").prefetch_related(
                "userfeedback_set"
            )
            logger.debug(
                f"Using indexed corpus query for doc {document_id}, corpus {corpus_id}"
            )

        else:
            # General queries - use standard optimization
            qs = qs.select_related("annotation_label", "creator")

        # Order by page and position for consistent results
        qs = qs.order_by("page", "bounding_box")

        if use_cache:
            # Cache the queryset (Django will cache the SQL, not results)
            cache.set(cache_key, qs, cls.CACHE_TTL)

        return qs

    @classmethod
    def get_annotation_summary(
        cls, document_id: int, corpus_id: int, use_mv: bool = True
    ) -> dict[str, Any]:
        """
        Get annotation summary statistics.
        Uses materialized view for performance when available.

        Args:
            document_id: Document ID
            corpus_id: Corpus ID
            use_mv: Whether to use materialized view

        Returns:
            Dictionary with summary statistics
        """
        cache_key = f"annotation_summary:{document_id}:{corpus_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        if use_mv:
            # Try to use materialized view first
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            annotation_count,
                            structural_count,
                            user_annotation_count,
                            analysis_count,
                            page_count,
                            pages_with_annotations,
                            first_annotated_page,
                            last_annotated_page
                        FROM annotation_summary_mv
                        WHERE document_id = %s AND corpus_id = %s
                    """,
                        [document_id, corpus_id],
                    )

                    row = cursor.fetchone()
                    if row:
                        summary = {
                            "annotation_count": row[0] or 0,
                            "structural_count": row[1] or 0,
                            "user_annotation_count": row[2] or 0,
                            "analysis_count": row[3] or 0,
                            "page_count": row[4] or 0,
                            "pages_with_annotations": row[5] or [],
                            "first_page": row[6],
                            "last_page": row[7],
                            "source": "materialized_view",
                        }
                        cache.set(cache_key, summary, cls.CACHE_TTL)
                        logger.debug(
                            f"Retrieved summary from MV for doc {document_id}, corpus {corpus_id}"
                        )
                        return summary

            except Exception as e:
                logger.warning(f"Failed to query materialized view: {e}")

        # Fallback to direct query
        from opencontractserver.annotations.models import Annotation

        qs = Annotation.objects.filter(document_id=document_id, corpus_id=corpus_id)

        summary = qs.aggregate(
            annotation_count=Count("id", filter=Q(structural=False)),
            structural_count=Count("id", filter=Q(structural=True)),
            user_annotation_count=Count(
                "id", filter=Q(structural=False, analysis_id__isnull=True)
            ),
            first_page=Min("page"),
            last_page=Max("page"),
        )

        # Get distinct analysis count
        summary["analysis_count"] = (
            qs.filter(analysis_id__isnull=False)
            .values("analysis_id")
            .distinct()
            .count()
        )

        # Get pages with annotations
        pages = qs.values_list("page", flat=True).distinct().order_by("page")
        summary["pages_with_annotations"] = list(pages)
        summary["page_count"] = len(summary["pages_with_annotations"])
        summary["source"] = "direct_query"

        cache.set(cache_key, summary, cls.CACHE_TTL)
        logger.debug(
            f"Retrieved summary from direct query for doc {document_id}, corpus {corpus_id}"
        )

        return summary

    @classmethod
    def get_navigation_annotations(
        cls,
        document_id: int,
        corpus_id: int,
        analysis_id: Optional[int] = None,
        use_mv: bool = True,
    ) -> QuerySet:
        """
        Get lightweight annotation data for navigation.
        Uses materialized view when beneficial.

        Args:
            document_id: Document ID
            corpus_id: Corpus ID
            analysis_id: Optional analysis filter
            use_mv: Whether to use materialized view

        Returns:
            QuerySet with navigation data
        """
        from opencontractserver.annotations.models import Annotation

        if use_mv and analysis_id is None:
            # Try materialized view for unfiltered navigation
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, page, bounding_box
                        FROM annotation_navigation_mv
                        WHERE document_id = %s AND corpus_id = %s
                        ORDER BY page, id
                    """,
                        [document_id, corpus_id],
                    )

                    results = []
                    for row in cursor.fetchall():
                        results.append(
                            {"id": row[0], "page": row[1], "bounding_box": row[2]}
                        )

                    if results:
                        logger.debug(
                            f"Retrieved {len(results)} navigation items from MV"
                        )
                        return results

            except Exception as e:
                logger.warning(f"Failed to query navigation MV: {e}")

        # Fallback to direct query
        qs = Annotation.objects.filter(
            document_id=document_id, corpus_id=corpus_id, structural=False
        )

        if analysis_id is not None:
            if analysis_id == 0:
                qs = qs.filter(analysis_id__isnull=True)
            else:
                qs = qs.filter(analysis_id=analysis_id)

        # Only fetch fields needed for navigation
        qs = qs.only("id", "page", "bounding_box").order_by("page", "id")

        logger.debug("Retrieved navigation items from direct query")
        return qs

    @classmethod
    def prefetch_for_graphql(cls, queryset: QuerySet) -> QuerySet:
        """
        Optimize queryset for GraphQL queries with proper prefetching.

        Args:
            queryset: Base annotation queryset

        Returns:
            Optimized queryset with prefetches
        """
        from opencontractserver.feedback.models import UserFeedback

        return queryset.select_related(
            "annotation_label", "creator", "analysis", "document", "corpus"
        ).prefetch_related(
            Prefetch(
                "userfeedback_set",
                queryset=UserFeedback.objects.select_related("creator"),
            ),
            "children",
            "embedding_set",
        )

    @classmethod
    def invalidate_cache(
        cls, document_id: Optional[int] = None, corpus_id: Optional[int] = None
    ):
        """
        Invalidate cached queries for a document/corpus.

        Args:
            document_id: Optional document ID
            corpus_id: Optional corpus ID
        """
        if document_id and corpus_id:
            # Specific invalidation
            pattern = f"*:{document_id}:{corpus_id}:*"
            logger.info(f"Invalidating cache for doc {document_id}, corpus {corpus_id}")
        elif document_id:
            pattern = f"*:{document_id}:*"
            logger.info(f"Invalidating cache for doc {document_id}")
        elif corpus_id:
            pattern = f"*:*:{corpus_id}:*"
            logger.info(f"Invalidating cache for corpus {corpus_id}")
        else:
            pattern = "doc_annotations:*"
            logger.info("Invalidating all annotation caches")

        try:
            cache.delete_pattern(pattern)
        except AttributeError:
            # Cache backend doesn't support pattern deletion
            logger.warning("Cache backend doesn't support pattern deletion")
