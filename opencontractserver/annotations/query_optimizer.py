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
        pages: Optional[list[int]] = None,
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
            page: Optional single page number filter (deprecated, use pages)
            pages: Optional list of page numbers to filter
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

        # Handle pages parameter - consolidate page and pages into a single list
        page_list = None
        if pages is not None and len(pages) > 0:
            page_list = pages
        elif page is not None:
            page_list = [page]

        # Build cache key including user info and page list
        user_id = user.id if user and hasattr(user, "id") else "anon"
        pages_str = ",".join(map(str, page_list)) if page_list else "all"
        cache_key = f"doc_annotations:{document_id}:{corpus_id}:{pages_str}:{structural}:{analysis_id}:{user_id}"

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

        if page_list is not None:
            if len(page_list) == 1:
                # Single page - use exact match (more efficient)
                qs = qs.filter(page=page_list[0])
            else:
                # Multiple pages - use IN clause
                qs = qs.filter(page__in=page_list)

        if structural is not None:
            qs = qs.filter(structural=structural)

        if analysis_id is not None:
            if analysis_id == 0:  # User annotations (no analysis)
                qs = qs.filter(analysis_id__isnull=True)
            else:
                qs = qs.filter(analysis_id=analysis_id)

        # Choose optimization strategy based on filters
        if page_list is not None:
            # Page-specific queries benefit from indexes
            qs = qs.select_related("annotation_label", "creator").prefetch_related(
                "user_feedback"
            )
            logger.debug(
                f"Using indexed page query for doc {document_id}, pages {page_list}"
            )

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


class RelationshipQueryOptimizer:
    """
    Query optimizer for relationship queries.
    Provides optimized querysets with caching and permission filtering.
    """

    # Cache configuration
    CACHE_TTL = 300  # 5 minutes

    @classmethod
    def _normalize_pages(cls, pages: Optional[list[int]]) -> str:
        """
        Normalize pages list for cache key generation.
        Returns 'all' for None, 'empty' for [], or comma-separated sorted unique list.
        """
        if pages is None:
            return "all"
        if len(pages) == 0:
            return "empty"
        try:
            unique_sorted_pages = sorted({int(p) for p in pages})
        except Exception:
            # Best-effort fallback
            unique_sorted_pages = pages
        return ",".join(str(p) for p in unique_sorted_pages)

    @classmethod
    def _get_cache_key(
        cls,
        document_id: int,
        user_id: Optional[int],
        corpus_id: Optional[int],
        pages: Optional[list[int]],
        structural: Optional[bool],
        analysis_id: Optional[int],
    ) -> str:
        """
        Build a stable cache key for relationship queries.
        """
        pages_part = cls._normalize_pages(pages)
        user_part = user_id if user_id is not None else "anon"
        corpus_part = corpus_id if corpus_id is not None else "any"
        analysis_part = analysis_id if analysis_id is not None else "any"
        structural_part = (
            "true" if structural is True else "false" if structural is False else "any"
        )
        return f"doc_relationships:{document_id}:{corpus_part}:{pages_part}:{analysis_part}:{structural_part}:{user_part}"  # noqa: E501

    @classmethod
    def _register_relationship_cache_key(
        cls,
        document_id: int,
        corpus_id: Optional[int],
        cache_key: str,
    ) -> None:
        """
        Register the generated cache key into per-document and per-(document, corpus)
        registries to enable explicit invalidation on cache backends that do not
        support pattern deletion.
        """
        try:
            # Doc-level registry
            doc_registry_key = f"doc_relationships:keys:{document_id}"
            doc_registry = cache.get(doc_registry_key) or []
            if cache_key not in doc_registry:
                doc_registry.append(cache_key)
                cache.set(doc_registry_key, doc_registry, cls.CACHE_TTL * 6)

            # Doc+corpus registry
            if corpus_id is not None:
                doc_corpus_registry_key = (
                    f"doc_relationships:keys:{document_id}:{corpus_id}"
                )
                doc_corpus_registry = cache.get(doc_corpus_registry_key) or []
                if cache_key not in doc_corpus_registry:
                    doc_corpus_registry.append(cache_key)
                    cache.set(
                        doc_corpus_registry_key, doc_corpus_registry, cls.CACHE_TTL * 6
                    )
        except Exception:
            # Best-effort only; skip if cache backend has issues
            pass

    @classmethod
    def _check_document_permission(cls, user, document_id: int) -> bool:
        """Check if user can access the document using a lean query."""
        from django.contrib.auth.models import AnonymousUser

        from opencontractserver.documents.models import Document
        from opencontractserver.types.enums import PermissionTypes
        from opencontractserver.utils.permissioning import user_has_permission_for_obj

        try:
            document = (
                Document.objects.select_related("creator")
                .only("id", "is_public", "creator_id", "creator__id")
                .order_by()
                .get(id=document_id)
            )

            if document.is_public:
                return True

            if (
                user is None
                or isinstance(user, AnonymousUser)
                or not getattr(user, "is_authenticated", False)
            ):
                return False

            if document.creator_id == getattr(user, "id", None) or getattr(
                user, "is_superuser", False
            ):
                return True

            return user_has_permission_for_obj(
                user, document, PermissionTypes.READ, include_group_permissions=True
            )
        except Document.DoesNotExist:
            return False

    @classmethod
    def _check_corpus_permission(cls, user, corpus_id: int) -> bool:
        """Check if user can access the corpus using a lean query."""
        from django.contrib.auth.models import AnonymousUser

        from opencontractserver.corpuses.models import Corpus
        from opencontractserver.types.enums import PermissionTypes
        from opencontractserver.utils.permissioning import user_has_permission_for_obj

        try:
            corpus = (
                Corpus.objects.select_related("creator")
                .only("id", "is_public", "creator_id", "creator__id")
                .order_by()
                .get(id=corpus_id)
            )

            if corpus.is_public:
                return True

            if (
                user is None
                or isinstance(user, AnonymousUser)
                or not getattr(user, "is_authenticated", False)
            ):
                return False

            if corpus.creator_id == getattr(user, "id", None) or getattr(
                user, "is_superuser", False
            ):
                return True

            return user_has_permission_for_obj(
                user, corpus, PermissionTypes.READ, include_group_permissions=True
            )
        except Corpus.DoesNotExist:
            return False

    @classmethod
    def _get_relationship_permission_filter(cls, user):
        """Get permission filter for relationships based on user."""
        from django.contrib.auth.models import AnonymousUser

        if isinstance(user, AnonymousUser) or not user:
            # Anonymous users can only see public and structural relationships
            return Q(is_public=True) | Q(structural=True)

        if user.is_superuser:
            # Superusers can see everything
            return Q()

        # Regular users can see:
        # 1. Their own relationships
        # 2. Public relationships
        # 3. Structural relationships
        return Q(is_public=True) | Q(creator=user) | Q(structural=True)

    @classmethod
    def get_document_relationships(
        cls,
        document_id: int,
        user=None,
        corpus_id: Optional[int] = None,
        pages: Optional[list[int]] = None,
        analysis_id: Optional[int] = None,
        structural: Optional[bool] = None,
        use_cache: bool = True,
    ) -> QuerySet:
        """
        Get optimized queryset for document relationships with permission filtering.

        Args:
            document_id: Document ID
            user: User object for permission filtering
            corpus_id: Optional corpus ID filter
            pages: Optional list of page numbers to filter
            analysis_id: Optional analysis ID filter
            structural: Optional structural filter
            use_cache: Whether to use caching

        Returns:
            Optimized QuerySet (empty if no permission)
        """
        from opencontractserver.annotations.models import Annotation, Relationship

        # Check document permission first
        if not cls._check_document_permission(user, document_id):
            logger.debug(f"User {user} denied access to document {document_id}")
            return Relationship.objects.none()

        # Check corpus permission if specified
        if corpus_id is not None and not cls._check_corpus_permission(user, corpus_id):
            logger.debug(f"User {user} denied access to corpus {corpus_id}")
            return Relationship.objects.none()

        # Build cache key
        user_id = user.id if user and hasattr(user, "id") else None
        cache_key = cls._get_cache_key(
            document_id=document_id,
            user_id=user_id,
            corpus_id=corpus_id,
            pages=pages,
            structural=structural,
            analysis_id=analysis_id,
        )

        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached

        # Treat explicit empty pages list as empty result
        from opencontractserver.annotations.models import (  # noqa: F811
            Annotation,
            Relationship,
        )

        if pages is not None and len(pages) == 0:
            return Relationship.objects.none()

        # Start with base query
        qs = Relationship.objects.filter(document_id=document_id)

        # Apply permission filter
        permission_filter = cls._get_relationship_permission_filter(user)
        qs = qs.filter(permission_filter)

        # Apply filters
        if corpus_id is not None:
            qs = qs.filter(Q(corpus_id=corpus_id) | Q(structural=True))
        else:
            # No corpus specified - only show structural relationships
            qs = qs.filter(structural=True)

        if structural is not None:
            qs = qs.filter(structural=structural)

        if analysis_id is not None:
            if analysis_id == 0:  # User relationships (no analysis)
                qs = qs.filter(Q(analysis_id__isnull=True) | Q(structural=True))
            else:
                qs = qs.filter(Q(analysis_id=analysis_id) | Q(structural=True))
        else:
            # No analysis specified - show only user-created and structural
            qs = qs.filter(Q(analysis__isnull=True) | Q(structural=True))

        # Filter by pages if specified
        if pages:
            # Get annotations on the specified pages
            page_annotations = Annotation.objects.filter(
                document_id=document_id, page__in=pages
            )
            if corpus_id is not None:
                page_annotations = page_annotations.filter(corpus_id=corpus_id)

            annotation_ids = page_annotations.values_list("id", flat=True)

            # Filter relationships that touch these pages
            qs = qs.filter(
                Q(source_annotations__in=annotation_ids)
                | Q(target_annotations__in=annotation_ids)
            ).distinct()

        # Prefetch strategy depends on caching intent
        qs = qs.select_related(
            "relationship_label", "creator", "corpus", "analysis", "analyzer"
        )

        if not use_cache:
            # Full prefetch for zero-query access to related data after evaluation
            source_prefetch = Prefetch(
                "source_annotations",
                queryset=Annotation.objects.select_related(
                    "annotation_label", "creator"
                ),
            )
            target_prefetch = Prefetch(
                "target_annotations",
                queryset=Annotation.objects.select_related(
                    "annotation_label", "creator"
                ),
            )
            qs = qs.prefetch_related(source_prefetch, target_prefetch)

        # Order by creation date for consistent results
        qs = qs.order_by("created")

        if use_cache:
            # Cache the queryset and register key for explicit invalidation later
            cache.set(cache_key, qs, cls.CACHE_TTL)
            cls._register_relationship_cache_key(document_id, corpus_id, cache_key)

        return qs

    @classmethod
    def get_relationship_summary(
        cls, document_id: int, corpus_id: int, user=None, use_cache: bool = True
    ) -> dict:
        """
        Get relationship summary statistics.
        Uses materialized view when available, falls back to direct query.
        """
        # Check permissions
        if not cls._check_document_permission(user, document_id):
            return {
                "document_id": document_id,
                "corpus_id": corpus_id,
                "relationship_count": 0,
                "label_types": 0,
                "pages_with_relationships": [],
                "source": "permission_denied",
            }

        if not cls._check_corpus_permission(user, corpus_id):
            return {
                "document_id": document_id,
                "corpus_id": corpus_id,
                "relationship_count": 0,
                "label_types": 0,
                "pages_with_relationships": [],
                "source": "permission_denied",
            }

        user_id = user.id if user and hasattr(user, "id") else "anon"
        cache_key = f"relationship_summary:{document_id}:{corpus_id}:{user_id}"

        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for relationship summary {cache_key}")
                return cached

        summary = {}

        # Try materialized view first
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        document_id,
                        corpus_id,
                        relationship_count,
                        label_types,
                        pages_with_relationships,
                        last_refreshed
                    FROM relationship_summary_mv
                    WHERE document_id = %s AND corpus_id = %s
                    """,
                    [document_id, corpus_id],
                )
                row = cursor.fetchone()

                if row:
                    summary = {
                        "document_id": row[0],
                        "corpus_id": row[1],
                        "relationship_count": row[2],
                        "label_types": row[3],
                        "pages_with_relationships": row[4] or [],
                        "last_refreshed": row[5],
                        "source": "materialized_view",
                    }
                    logger.debug(
                        f"Loaded relationship summary from MV for doc {document_id}"
                    )
                    cache.set(cache_key, summary, cls.CACHE_TTL)
                    # Track users who have cached summaries for this (doc, corpus)
                    if user_id != "anon":
                        try:
                            registry_key = (
                                f"relationship_summary:users:{document_id}:{corpus_id}"
                            )
                            registry = cache.get(registry_key) or []
                            if user_id not in registry:
                                registry.append(user_id)
                                cache.set(registry_key, registry, cls.CACHE_TTL * 6)
                        except Exception:
                            pass
                    return summary

        except Exception as e:
            logger.warning(f"Failed to load from relationship_summary_mv: {e}")

        # Fallback to direct query
        logger.debug(
            f"Falling back to direct query for relationship summary {document_id}"
        )

        qs = cls.get_document_relationships(
            document_id=document_id, user=user, corpus_id=corpus_id, use_cache=False
        )

        summary["document_id"] = document_id
        summary["corpus_id"] = corpus_id
        summary["relationship_count"] = qs.count()

        # Count distinct label types
        summary["label_types"] = qs.values("relationship_label").distinct().count()

        # Get pages with relationships
        from opencontractserver.annotations.models import Annotation

        # Get all annotation IDs involved in relationships
        source_ann_ids = qs.values_list("source_annotations", flat=True)
        target_ann_ids = qs.values_list("target_annotations", flat=True)
        all_ann_ids = set(source_ann_ids) | set(target_ann_ids)

        # Get distinct pages from these annotations
        pages = (
            Annotation.objects.filter(id__in=all_ann_ids)
            .values_list("page", flat=True)
            .distinct()
            .order_by("page")
        )

        summary["pages_with_relationships"] = list(pages)
        summary["source"] = "direct_query"

        cache.set(cache_key, summary, cls.CACHE_TTL)
        # Track users who have cached summaries for this (doc, corpus)
        if user_id != "anon":
            try:
                registry_key = f"relationship_summary:users:{document_id}:{corpus_id}"
                registry = cache.get(registry_key) or []
                if user_id not in registry:
                    registry.append(user_id)
                    cache.set(registry_key, registry, cls.CACHE_TTL * 6)
            except Exception:
                pass
        return summary

    @classmethod
    def invalidate_cache(
        cls, document_id: Optional[int] = None, corpus_id: Optional[int] = None
    ):
        """Invalidate cached relationship data."""
        # Best-effort explicit deletion using registries
        deleted_any = False

        if document_id and corpus_id:
            logger.info(
                f"Invalidating relationship cache for doc {document_id}, corpus {corpus_id}"
            )
            try:
                doc_corpus_registry_key = (
                    f"doc_relationships:keys:{document_id}:{corpus_id}"
                )
                keys = cache.get(doc_corpus_registry_key) or []
                for k in keys:
                    cache.delete(k)
                    deleted_any = True
                # Clear the registry after deletion
                cache.delete(doc_corpus_registry_key)
            except Exception:
                pass

            # Invalidate relationship summaries for registered users for this (doc, corpus)
            try:
                registry_key = f"relationship_summary:users:{document_id}:{corpus_id}"
                users = cache.get(registry_key) or []
                for user_id in users:
                    user_key = (
                        f"relationship_summary:{document_id}:{corpus_id}:{user_id}"
                    )
                    cache.delete(user_key)
                    deleted_any = True
                cache.delete(registry_key)
            except Exception:
                pass

        elif document_id:
            logger.info(f"Invalidating relationship cache for doc {document_id}")
            try:
                doc_registry_key = f"doc_relationships:keys:{document_id}"
                keys = cache.get(doc_registry_key) or []
                for k in keys:
                    cache.delete(k)
                    deleted_any = True
                cache.delete(doc_registry_key)
            except Exception:
                pass

        elif corpus_id:
            logger.info(f"Invalidating relationship cache for corpus {corpus_id}")
            # No registry by corpus only; will fall back to pattern

        else:
            logger.info("Invalidating all relationship caches")

        # Fallback to pattern deletion if supported and explicit deletion didn't cover all cases
        try:
            if document_id and corpus_id:
                pattern = f"doc_relationships:{document_id}:{corpus_id}:*"
            elif document_id:
                pattern = f"doc_relationships:{document_id}:*"
            elif corpus_id:
                pattern = f"doc_relationships:*:{corpus_id}:*"
            else:
                pattern = "doc_relationships:*"

            cache.delete_pattern(pattern)
            cache.delete_pattern("relationship_summary:*")
        except AttributeError:
            if not deleted_any:
                # Cache backend doesn't support pattern deletion and no explicit keys were deleted
                logger.warning(
                    "Cache backend doesn't support pattern deletion and no registry keys found"
                )
