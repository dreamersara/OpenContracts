"""
Query optimizer for annotation queries.
Provides optimized querysets based on access patterns.
"""

import logging
from typing import Any, Optional

from django.contrib.auth.models import AnonymousUser
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
    def _check_document_permission(cls, user, document_id: int) -> bool:
        """
        Check if user has permission to access a document.

        Args:
            user: User object (can be AnonymousUser)
            document_id: Document ID

        Returns:
            True if user can access the document, False otherwise
        """
        from opencontractserver.documents.models import Document
        from opencontractserver.types.enums import PermissionTypes
        from opencontractserver.utils.permissioning import user_has_permission_for_obj

        try:
            # Optimize by only fetching needed fields and using select_related for creator
            document = (
                Document.objects.select_related("creator")
                .only("id", "is_public", "creator_id", "creator__id")
                .get(id=document_id)
            )

            # Check if document is public
            if document.is_public:
                return True

            # Anonymous users can only see public documents
            if (
                user is None
                or isinstance(user, AnonymousUser)
                or not user.is_authenticated
            ):
                return False

            # Check if user is the creator (now no extra query due to select_related)
            if document.creator_id == user.id:
                return True

            # Check if user is superuser
            if user.is_superuser:
                return True

            # Check explicit permissions
            return user_has_permission_for_obj(
                user, document, PermissionTypes.READ, include_group_permissions=True
            )
        except Document.DoesNotExist:
            return False

    @classmethod
    def _check_corpus_permission(cls, user, corpus_id: int) -> bool:
        """
        Check if user has permission to access a corpus.

        Args:
            user: User object (can be AnonymousUser)
            corpus_id: Corpus ID

        Returns:
            True if user can access the corpus, False otherwise
        """
        from opencontractserver.corpuses.models import Corpus
        from opencontractserver.types.enums import PermissionTypes
        from opencontractserver.utils.permissioning import user_has_permission_for_obj

        try:
            # Optimize by only fetching needed fields and using select_related for creator
            corpus = (
                Corpus.objects.select_related("creator")
                .only("id", "is_public", "creator_id", "creator__id")
                .get(id=corpus_id)
            )

            # Check if corpus is public
            if corpus.is_public:
                return True

            # Anonymous users can only see public corpora
            if (
                user is None
                or isinstance(user, AnonymousUser)
                or not user.is_authenticated
            ):
                return False

            # Check if user is the creator (now no extra query due to select_related)
            if corpus.creator_id == user.id:
                return True

            # Check if user is superuser
            if user.is_superuser:
                return True

            # Check explicit permissions
            return user_has_permission_for_obj(
                user, corpus, PermissionTypes.READ, include_group_permissions=True
            )
        except Corpus.DoesNotExist:
            return False

    @classmethod
    def _get_annotation_permission_filter(cls, user) -> Q:
        """
        Get permission filter for annotations based on user.

        Args:
            user: User object (can be AnonymousUser)

        Returns:
            Q object for filtering annotations
        """
        # Superuser sees everything
        if user and hasattr(user, "is_superuser") and user.is_superuser:
            return Q()

        # Anonymous users or unauthenticated users only see public annotations + structural
        if user is None or isinstance(user, AnonymousUser) or not user.is_authenticated:
            # Structural annotations are always visible if doc is accessible
            return Q(is_public=True) | Q(structural=True)

        # Regular users see:
        # 1. Public annotations
        # 2. Annotations they created
        # 3. Structural annotations (they're typically always visible if doc is accessible)
        return Q(is_public=True) | Q(creator=user) | Q(structural=True)

    @classmethod
    def get_document_annotations(
        cls,
        document_id: int,
        user=None,
        corpus_id: Optional[int] = None,
        page: Optional[int] = None,
        structural: Optional[bool] = None,
        analysis_id: Optional[int] = None,
        use_cache: bool = True,
    ) -> QuerySet:
        """
        Get optimized queryset for document annotations with permission filtering.

        Args:
            document_id: Document ID
            user: User object for permission filtering
            corpus_id: Optional corpus ID filter
            page: Optional page number filter
            structural: Optional structural filter
            analysis_id: Optional analysis ID filter
            use_cache: Whether to use caching

        Returns:
            Optimized QuerySet (empty if no permission)
        """
        from opencontractserver.annotations.models import Annotation

        # Check document permission first
        if not cls._check_document_permission(user, document_id):
            logger.debug(f"User {user} denied access to document {document_id}")
            return Annotation.objects.none()

        # Check corpus permission if specified
        if corpus_id is not None and not cls._check_corpus_permission(user, corpus_id):
            logger.debug(f"User {user} denied access to corpus {corpus_id}")
            return Annotation.objects.none()

        # Build cache key including user info
        user_id = user.id if user and hasattr(user, "id") else "anon"
        cache_key = f"doc_annotations:{document_id}:{corpus_id}:{page}:{structural}:{analysis_id}:{user_id}"

        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached

        # Start with base query
        qs = Annotation.objects.filter(document_id=document_id)

        # Apply permission filter for annotations
        permission_filter = cls._get_annotation_permission_filter(user)
        qs = qs.filter(permission_filter)

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
            qs = qs.select_related("annotation_label", "creator").prefetch_related(
                "user_feedback"
            )
            logger.debug(f"Using indexed page query for doc {document_id}, page {page}")

        elif structural is False and corpus_id is not None:
            # Non-structural corpus queries benefit from our composite index
            qs = qs.select_related("annotation_label", "creator").prefetch_related(
                "user_feedback"
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
        cls, document_id: int, corpus_id: int, user=None, use_mv: bool = True
    ) -> dict[str, Any]:
        """
        Get annotation summary statistics with permission filtering.
        Uses materialized view for performance when available.

        Args:
            document_id: Document ID
            corpus_id: Corpus ID
            user: User object for permission filtering
            use_mv: Whether to use materialized view

        Returns:
            Dictionary with summary statistics (empty if no permission)
        """
        # Check permissions first
        if not cls._check_document_permission(user, document_id):
            logger.debug(f"User {user} denied access to document {document_id}")
            return {
                "annotation_count": 0,
                "structural_count": 0,
                "user_annotation_count": 0,
                "analysis_count": 0,
                "page_count": 0,
                "pages_with_annotations": [],
                "first_page": None,
                "last_page": None,
                "source": "no_permission",
            }

        if not cls._check_corpus_permission(user, corpus_id):
            logger.debug(f"User {user} denied access to corpus {corpus_id}")
            return {
                "annotation_count": 0,
                "structural_count": 0,
                "user_annotation_count": 0,
                "analysis_count": 0,
                "page_count": 0,
                "pages_with_annotations": [],
                "first_page": None,
                "last_page": None,
                "source": "no_permission",
            }

        user_id = user.id if user and hasattr(user, "id") else "anon"
        cache_key = f"annotation_summary:{document_id}:{corpus_id}:{user_id}"
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
                        # Track users who have cached summaries for this (doc, corpus)
                        if user_id != "anon":
                            registry_key = (
                                f"annotation_summary:users:{document_id}:{corpus_id}"
                            )
                            try:
                                registry = cache.get(registry_key) or []
                                if user_id not in registry:
                                    registry.append(user_id)
                                    # Keep registry around longer than summary TTL
                                    cache.set(registry_key, registry, cls.CACHE_TTL * 6)
                            except Exception:
                                # Best-effort registry update; ignore cache backend issues
                                pass
                        logger.debug(
                            f"Retrieved summary from MV for doc {document_id}, corpus {corpus_id}"
                        )
                        return summary

            except Exception as e:
                logger.warning(f"Failed to query materialized view: {e}")

        # Fallback to direct query
        from opencontractserver.annotations.models import Annotation

        qs = Annotation.objects.filter(document_id=document_id, corpus_id=corpus_id)

        # Apply permission filter
        permission_filter = cls._get_annotation_permission_filter(user)
        qs = qs.filter(permission_filter)

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
        # Track users who have cached summaries for this (doc, corpus)
        if user_id != "anon":
            registry_key = f"annotation_summary:users:{document_id}:{corpus_id}"
            try:
                registry = cache.get(registry_key) or []
                if user_id not in registry:
                    registry.append(user_id)
                    cache.set(registry_key, registry, cls.CACHE_TTL * 6)
            except Exception:
                pass
        logger.debug(
            f"Retrieved summary from direct query for doc {document_id}, corpus {corpus_id}"
        )

        return summary

    @classmethod
    def get_navigation_annotations(
        cls,
        document_id: int,
        corpus_id: int,
        user=None,
        analysis_id: Optional[int] = None,
        use_mv: bool = True,
    ) -> QuerySet:
        """
        Get lightweight annotation data for navigation with permission filtering.
        Uses materialized view when beneficial.

        Args:
            document_id: Document ID
            corpus_id: Corpus ID
            user: User object for permission filtering
            analysis_id: Optional analysis filter
            use_mv: Whether to use materialized view

        Returns:
            QuerySet with navigation data (empty if no permission)
        """
        from opencontractserver.annotations.models import Annotation

        # Check permissions first
        if not cls._check_document_permission(user, document_id):
            logger.debug(f"User {user} denied access to document {document_id}")
            return []

        if not cls._check_corpus_permission(user, corpus_id):
            logger.debug(f"User {user} denied access to corpus {corpus_id}")
            return []

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

        # Apply permission filter
        permission_filter = cls._get_annotation_permission_filter(user)
        qs = qs.filter(permission_filter)

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
