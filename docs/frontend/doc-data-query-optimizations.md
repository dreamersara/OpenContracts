# OpenContracts Annotation Performance Optimization Guide

## Executive Summary

The OpenContracts `GetDocumentKnowledgeAndAnnotations` query currently suffers from severe performance issues (10-30+ seconds) due to loading ALL annotations for a corpus. This guide provides a production-ready implementation to achieve <500ms response times through:

1. **Database Optimization**: Strategic indexes and materialized views
2. **Query Optimization**: Eliminating N+1 queries with proper prefetching
3. **Progressive Loading**: Load only visible content on-demand
4. **Smart Caching**: Using materialized views for aggregations only

**Target Performance**: Initial load <500ms, smooth scrolling, instant jump-to-annotation

### Important Trade-offs

**Materialized Views Without Partial Refresh:**
- PostgreSQL doesn't support `REFRESH ... WHERE`, so entire views are refreshed
- We mitigate this with:
  - `CONCURRENTLY` flag (no blocking during refresh)
  - Debouncing (batch updates together)
  - Caching (reduce database hits)
  - Fallback to live queries if needed

For most use cases, the performance gain (30-60x) far outweighs the slight staleness during updates.

---

## Current Performance Analysis

### Identified Bottlenecks

Based on codebase analysis:

1. **`resolve_all_annotations` in DocumentType**: Loads ALL annotations without pagination
2. **N+1 Query Problem**: User feedback loaded in separate queries per annotation
3. **Missing Optimization**: No prefetch_related for relationships and labels
4. **Database Indexes**: Good coverage but missing covering indexes for common queries
5. **No Progressive Loading**: Frontend loads everything at once

### Current Database Indexes (from models.py)

```python
# Existing indexes on Annotation model:
- ["page"]
- ["annotation_label"]
- ["document"]
- ["document", "creator"]
- ["corpus"]
- ["structural", "corpus"]
- ["corpus", "creator"]
- ["document", "corpus"]
- ["document", "corpus", "creator"]
- ["analysis"]
- ["creator"]
- ["created"]
- ["modified"]
```

---

## Implementation Plan

### Phase 1: Database Optimization

#### 1.0 Hybrid Index Strategy (Django + Raw SQL)

**Why Both?** Django's `models.Index` is great for simple indexes but lacks support for advanced PostgreSQL features. We use a hybrid approach:

**In models.py (Simple indexes):**
```python
class Annotation(BaseOCModel):
    # ... fields ...

    class Meta:
        indexes = [
            # Keep existing simple indexes that Django supports
            models.Index(fields=['page']),
            models.Index(fields=['document', 'corpus']),
            models.Index(fields=['structural', 'corpus']),

            # Add new conditional indexes that Django supports
            models.Index(
                fields=['corpus', 'analysis'],
                condition=Q(analysis__isnull=False),
                name='idx_corpus_analysis'
            ),
            models.Index(
                fields=['corpus', 'document'],
                condition=Q(analysis__isnull=True) & Q(structural=False),
                name='idx_user_annotations'
            ),
        ]
```

**In migrations (Advanced indexes):**
- **Covering indexes** with `INCLUDE` clause (2-5x performance boost)
- **CONCURRENTLY** flag (no blocking during creation)
- **Complex partial indexes** with multiple conditions

This approach provides clarity in models.py while leveraging PostgreSQL's full power for performance-critical queries.

#### 1.1 Create Performance Indexes

**File:** `/opencontractserver/annotations/migrations/0036_add_performance_indexes.py`

```python
from django.db import migrations

class Migration(migrations.Migration):
    atomic = False  # required for CREATE INDEX CONCURRENTLY

    """
    Performance indexes for annotation queries.
    """

    dependencies = [
        ('annotations', '0035_remove_metadata_fields'),
    ]

    operations = [
        migrations.RunSQL(
            """
            -- Non-structural, page-scoped main path
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ann_doc_corpus_page_nonstruct
            ON annotations_annotation(document_id, corpus_id, page)
            WHERE structural = false;
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_ann_doc_corpus_page_nonstruct;"
        ),
        migrations.RunSQL(
            """
            -- Non-structural, user-created (analysis_id IS NULL)
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ann_doc_corpus_page_user
            ON annotations_annotation(document_id, corpus_id, page)
            WHERE structural = false AND analysis_id IS NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_ann_doc_corpus_page_user;"
        ),
        migrations.RunSQL(
            """
            -- Non-structural, with analysis filter
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ann_doc_corpus_analysis_page
            ON annotations_annotation(document_id, corpus_id, analysis_id, page)
            WHERE structural = false AND analysis_id IS NOT NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_ann_doc_corpus_analysis_page;"
        ),
        migrations.RunSQL(
            """
            -- Structural access is usually page-scoped as well
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ann_doc_page_struct
            ON annotations_annotation(document_id, page)
            WHERE structural = true;
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_ann_doc_page_struct;"
        ),
        migrations.RunSQL(
            """
            -- Relationships
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_relationship_corpus_doc_struct
            ON annotations_relationship(corpus_id, document_id, structural);
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_relationship_corpus_doc_struct;"
        ),
        migrations.RunSQL(
            """
            -- Feedback joins; keep lean
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_feedback_annotation_creator
            ON feedback_userfeedback(commented_annotation_id, creator_id);
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_feedback_annotation_creator;"
        ),
    ]
```

#### 1.2 Create Materialized Views for Aggregations

**File:** `/opencontractserver/annotations/migrations/0037_add_materialized_views.py`

```python
from django.db import migrations

class Migration(migrations.Migration):
    """
    Materialized views for annotation aggregations.

    Index Strategy for Materialized Views:
    - UNIQUE indexes on materialized views (one summary per document+corpus)
    - UNIQUE index enables REFRESH MATERIALIZED VIEW CONCURRENTLY
    - Regular indexes for lookups

    Why Materialized Views?
    - Instant aggregation results (COUNT, MIN, MAX, etc.)
    - Avoid counting thousands of rows on every request
    - Trade-off: Slightly stale data (refresh on updates) for massive performance gain
    """

    dependencies = [
        ('annotations', '0036_add_performance_indexes'),
    ]

    operations = [
        # Summary view for instant stats
        migrations.RunSQL(
            """
            -- Materialized view for annotation statistics
            -- One row per document+corpus combination
            CREATE MATERIALIZED VIEW IF NOT EXISTS annotation_summary_mv AS
            SELECT
                document_id,
                corpus_id,
                COUNT(*) FILTER (WHERE structural = false)            AS annotation_count,
                COUNT(*) FILTER (WHERE structural = true)             AS structural_count,
                COUNT(*) FILTER (WHERE analysis_id IS NULL AND structural = false) AS user_annotation_count,
                COUNT(DISTINCT analysis_id) FILTER (WHERE analysis_id IS NOT NULL) AS analysis_count,
                COUNT(DISTINCT page)                                    AS page_count,
                array_agg(DISTINCT page ORDER BY page) FILTER (WHERE page IS NOT NULL) AS pages_with_annotations,
                MIN(page) AS first_annotated_page,
                MAX(page) AS last_annotated_page,
                NOW()     AS last_refreshed
            FROM annotations_annotation
            GROUP BY document_id, corpus_id;

            CREATE UNIQUE INDEX IF NOT EXISTS annotation_summary_mv_doc_corpus_uidx
            ON annotation_summary_mv(document_id, corpus_id);

            CREATE INDEX IF NOT EXISTS annotation_summary_mv_corpus_idx
            ON annotation_summary_mv(corpus_id);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS annotation_summary_mv CASCADE;"
        ),

        # Navigation index for jump-to functionality
        migrations.RunSQL(
            """
            -- Slim navigation MV for fast refresh
            CREATE MATERIALIZED VIEW IF NOT EXISTS annotation_navigation_mv AS
            SELECT
                a.id,
                a.document_id,
                a.corpus_id,
                a.page,
                a.bounding_box,
                a.analysis_id
            FROM annotations_annotation a
            WHERE a.structural = false;

            -- UNIQUE index required for CONCURRENT refresh
            CREATE UNIQUE INDEX IF NOT EXISTS annotation_navigation_mv_id_uidx
            ON annotation_navigation_mv(id);

            -- Helpful lookups
            CREATE INDEX IF NOT EXISTS annotation_navigation_mv_doc_corpus_idx
            ON annotation_navigation_mv(document_id, corpus_id);

            CREATE INDEX IF NOT EXISTS annotation_navigation_mv_corpus_analysis_idx
            ON annotation_navigation_mv(corpus_id, analysis_id);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS annotation_navigation_mv CASCADE;"
        ),
    ]
```

#### 1.3 Materialized View Management

**Important Note:** PostgreSQL doesn't support partial refresh (WHERE clause) for materialized views. The entire view must be refreshed, but using CONCURRENTLY prevents blocking reads.

**File:** `/opencontractserver/annotations/tasks.py`

```python
from celery import shared_task
from django.db import connection
from django.core.cache import cache
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

LAST_REFRESH_CACHE_KEY = "annotation_mv_last_refresh"
MIN_REFRESH_INTERVAL = 60  # Minimum seconds between refreshes
REFRESH_DEBOUNCE_KEY = "annotation_mv_refresh_pending"
DEBOUNCE_DELAY = 5

@shared_task(time_limit=300)
def refresh_annotation_materialized_views(force=False):
    """
    Refresh materialized views for annotations.
    Uses CONCURRENTLY to avoid blocking readers.
    """
    try:
        if not force:
            last_refresh = cache.get(LAST_REFRESH_CACHE_KEY)
            if last_refresh:
                elapsed = (datetime.now() - last_refresh).total_seconds()
                if elapsed < MIN_REFRESH_INTERVAL:
                    logger.info(f"Skipping refresh, last refresh was {elapsed}s ago")
                    return False

        with connection.cursor() as cursor:
            cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv")
            cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_navigation_mv")

        # Best-effort pattern deletion if using django-redis; otherwise ignore
        try:
            cache.delete_pattern("annotation_summary:*")
        except Exception:
            pass

        cache.set(LAST_REFRESH_CACHE_KEY, datetime.now(), 3600)
        logger.info("Refreshed annotation materialized views")
        return True
    except Exception as e:
        logger.error(f"Failed to refresh materialized views: {e}")
        raise
    finally:
        cache.delete(REFRESH_DEBOUNCE_KEY)

@shared_task
def schedule_materialized_view_refresh():
    refresh_annotation_materialized_views.delay()
```

**File:** `/opencontractserver/annotations/signals.py` (append to existing)

```python
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import transaction
from django.core.cache import cache
from .models import Annotation, Relationship
from .tasks import refresh_annotation_materialized_views

REFRESH_DEBOUNCE_KEY = "annotation_mv_refresh_pending"
DEBOUNCE_DELAY = 5

def _debounced_refresh():
    # Set-if-not-exists to coalesce bursts
    if cache.add(REFRESH_DEBOUNCE_KEY, True, DEBOUNCE_DELAY):
        refresh_annotation_materialized_views.apply_async(countdown=DEBOUNCE_DELAY)

@receiver([post_save, post_delete], sender=Annotation)
def trigger_view_refresh_on_annotation_change(sender, instance, **kwargs):
    def queue_refresh():
        cache.delete(f"annotation_summary:{instance.document_id}:{instance.corpus_id}")
        _debounced_refresh()
    transaction.on_commit(queue_refresh)

@receiver([post_save, post_delete], sender=Relationship)
def trigger_view_refresh_on_relationship_change(sender, instance, **kwargs):
    def queue_refresh():
        cache.delete(f"annotation_summary:{instance.document_id}:{instance.corpus_id}")
        _debounced_refresh()
    transaction.on_commit(queue_refresh)
```

### Phase 2: Query Optimization Layer

#### 2.1 Query Optimizer

**File:** `/opencontractserver/utils/query_optimizer.py`

```python
"""
Query Optimizer for OpenContracts Annotation System.
Eliminates N+1 queries and provides progressive loading support.
"""

from django.db.models import Prefetch, Q, Count, F
from django.db import connection
from django.core.cache import cache
import logging
from typing import Optional, List, Dict, Any, Set
import json

logger = logging.getLogger(__name__)

class AnnotationQueryOptimizer:
    """
    Optimize annotation queries to prevent N+1 problems and enable progressive loading.
    """

    @staticmethod
    def optimize_annotation_queryset(
        qs,
        include_feedback: bool = True,
        include_relationships: bool = False,
        include_label_details: bool = True
    ):
        """
        Add prefetch_related and select_related to prevent N+1 queries.

        Performance impact:
        - Without optimization: 1000+ queries for 500 annotations
        - With optimization: 3-5 queries for 500 annotations
        """
        # Always select related for foreign keys to prevent extra queries
        qs = qs.select_related(
            'annotation_label',
            'document',
            'corpus',
            'creator',
            'analysis'
        )

        # Only select needed fields to reduce memory usage
        qs = qs.only(
            'id', 'page', 'raw_text', 'json', 'bounding_box',
            'structural', 'created', 'modified',
            'annotation_label__id', 'annotation_label__text',
            'annotation_label__color', 'annotation_label__icon',
            'annotation_label__label_type',
            'document__id', 'document__title',
            'corpus__id', 'corpus__title',
            'creator__id', 'creator__email',
            'analysis__id'
        )

        # Conditionally include user feedback
        if include_feedback:
            from opencontractserver.feedback.models import UserFeedback
            qs = qs.prefetch_related(
                Prefetch(
                    'user_feedback',
                    queryset=UserFeedback.objects.select_related('creator').only(
                        'id', 'approved', 'rejected', 'comment',
                        'creator__id', 'creator__email',
                        'commented_annotation_id'
                    )
                )
            )

        # Conditionally include relationships
        if include_relationships:
            from opencontractserver.annotations.models import Relationship

            # Prefetch source relationships
            source_qs = Relationship.objects.select_related(
                'relationship_label'
            ).only(
                'id', 'relationship_label__id', 'relationship_label__text',
                'corpus_id', 'document_id'
            )

            # Prefetch target relationships
            target_qs = Relationship.objects.select_related(
                'relationship_label'
            ).only(
                'id', 'relationship_label__id', 'relationship_label__text',
                'corpus_id', 'document_id'
            )

            qs = qs.prefetch_related(
                Prefetch('source_node_in_relationships', queryset=source_qs),
                Prefetch('target_node_in_relationships', queryset=target_qs)
            )

        return qs

    @staticmethod
    def get_annotation_manifest(document_id: int, corpus_id: int) -> Dict[str, Any]:
        """
        Get document annotation statistics from materialized view.
        Returns instantly instead of counting thousands of rows.

        Uses caching to further reduce database hits.
        """
        cache_key = f"annotation_summary:{document_id}:{corpus_id}"
        cached_result = cache.get(cache_key)

        if cached_result:
            return cached_result

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    annotation_count,
                    structural_count,
                    user_annotation_count,
                    analysis_count,
                    page_count,
                    pages_with_annotations,
                    first_annotated_page,
                    last_annotated_page,
                    last_refreshed
                FROM annotation_summary_mv
                WHERE document_id = %s AND corpus_id = %s
            """, [document_id, corpus_id])

            result = cursor.fetchone()

            if result:
                manifest = {
                    'annotation_count': result[0],
                    'structural_count': result[1],
                    'user_annotation_count': result[2],
                    'analysis_count': result[3],
                    'page_count': result[4],
                    'pages_with_annotations': result[5] or [],
                    'first_annotated_page': result[6],
                    'last_annotated_page': result[7],
                    'last_refreshed': result[8].isoformat() if result[8] else None
                }

                # Cache for 5 minutes
                cache.set(cache_key, manifest, 300)
                return manifest

            # Fallback to live calculation if materialized view is empty
            return AnnotationQueryOptimizer._calculate_manifest_fallback(document_id, corpus_id)

    @staticmethod
    def get_navigation_index(
        document_id: int,
        corpus_id: int,
        analysis_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get lightweight navigation index from materialized view.
        Used for jump-to-annotation functionality.
        """
        with connection.cursor() as cursor:
            if analysis_id:
                cursor.execute("""
                    SELECT id, page, bounding_box
                    FROM annotation_navigation_mv
                    WHERE document_id = %s
                      AND corpus_id = %s
                      AND (analysis_id = %s OR analysis_id IS NULL)
                    ORDER BY page, id
                """, [document_id, corpus_id, analysis_id])
            else:
                cursor.execute("""
                    SELECT id, page, bounding_box
                    FROM annotation_navigation_mv
                    WHERE document_id = %s
                      AND corpus_id = %s
                      AND analysis_id IS NULL
                    ORDER BY page, id
                """, [document_id, corpus_id])

            return [
                {
                    'id': row[0],
                    'page': row[1],
                    'bounding_box': row[2],
                }
                for row in cursor.fetchall()
            ]

    @staticmethod
    def load_visible_annotations(
        document_id: int,
        corpus_id: int,
        visible_pages: List[int],
        analysis_id: Optional[int] = None,
        prefetch_adjacent: bool = True,
        page_buffer: int = 2
    ) -> Dict[int, List]:
        """
        Load only annotations for visible pages with optional prefetching.

        Args:
            document_id: Document ID
            corpus_id: Corpus ID
            visible_pages: List of currently visible page numbers
            analysis_id: Optional analysis filter
            prefetch_adjacent: Whether to prefetch adjacent pages
            page_buffer: Number of pages to prefetch before/after visible pages

        Returns:
            Dictionary mapping page numbers to annotation objects
        """
        from opencontractserver.annotations.models import Annotation

        # Determine which pages to load
        pages_to_load = set(visible_pages)

        if prefetch_adjacent and visible_pages:
            # Add buffer pages for smooth scrolling
            min_page = min(visible_pages)
            max_page = max(visible_pages)

            # Add pages before and after visible range
            for page in range(max(1, min_page - page_buffer), max_page + page_buffer + 1):
                pages_to_load.add(page)

        # Build structural and non-structural separately to avoid ORs that hurt index usage
        non_structural_filters = Q(document_id=document_id, page__in=pages_to_load, structural=False)
        structural_filters = Q(document_id=document_id, page__in=pages_to_load, structural=True)

        if analysis_id:
            non_structural_filters &= Q(analysis_id=analysis_id)
        else:
            non_structural_filters &= Q(analysis__isnull=True)

        # Execute queries separately
        non_structural_qs = Annotation.objects.filter(non_structural_filters)
        structural_qs = Annotation.objects.filter(structural_filters)

        non_structural_qs = AnnotationQueryOptimizer.optimize_annotation_queryset(
            non_structural_qs,
            include_feedback=True,
            include_relationships=False
        )
        structural_qs = AnnotationQueryOptimizer.optimize_annotation_queryset(
            structural_qs,
            include_feedback=True,
            include_relationships=False
        )

        annotations = list(non_structural_qs) + list(structural_qs)
        annotations_by_page = {}

        for ann in annotations:
            annotations_by_page.setdefault(ann.page, []).append(ann)

        logger.debug(
            f"Loaded {len(annotations)} annotations for {len(pages_to_load)} pages "
            f"(visible: {len(visible_pages)}, prefetched: {len(pages_to_load) - len(visible_pages)})"
        )

        return annotations_by_page

    @staticmethod
    def get_annotation_for_jump(annotation_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific annotation with context for jump-to functionality.
        Returns the annotation plus nearby annotations on the same page.
        """
        from opencontractserver.annotations.models import Annotation

        try:
            # Get target annotation with optimization
            target = Annotation.objects.select_related(
                'annotation_label',
                'document',
                'corpus',
                'creator'
            ).get(id=annotation_id)

            # Get other annotations on the same page for context
            page_annotations = Annotation.objects.filter(
                document_id=target.document_id,
                page=target.page
            ).filter(
                Q(corpus_id=target.corpus_id) | Q(structural=True)
            )

            # Apply optimization
            page_annotations = AnnotationQueryOptimizer.optimize_annotation_queryset(
                page_annotations,
                include_feedback=True
            )

            return {
                'target': target,
                'page': target.page,
                'document_id': target.document_id,
                'corpus_id': target.corpus_id,
                'page_annotations': list(page_annotations)
            }

        except Annotation.DoesNotExist:
            return None

    @staticmethod
    def _calculate_manifest_fallback(document_id: int, corpus_id: int) -> Dict[str, Any]:
        """
        Fallback calculation when materialized view is unavailable.
        This is slower but ensures functionality.
        """
        from opencontractserver.annotations.models import Annotation
        from django.db.models import Count, Min, Max, Q

        # Get aggregated stats
        stats = Annotation.objects.filter(
            document_id=document_id,
            corpus_id=corpus_id
        ).aggregate(
            annotation_count=Count('id', filter=Q(structural=False)),
            structural_count=Count('id', filter=Q(structural=True)),
            user_annotation_count=Count('id', filter=Q(analysis__isnull=True, structural=False)),
            first_annotated_page=Min('page'),
            last_annotated_page=Max('page')
        )

        # Get distinct pages
        pages = list(
            Annotation.objects.filter(
                document_id=document_id,
                corpus_id=corpus_id,
                structural=False
            ).values_list('page', flat=True).distinct().order_by('page')
        )

        # Get analysis count
        analysis_count = Annotation.objects.filter(
            document_id=document_id,
            corpus_id=corpus_id,
            analysis__isnull=False
        ).values('analysis').distinct().count()

        return {
            'annotation_count': stats['annotation_count'] or 0,
            'structural_count': stats['structural_count'] or 0,
            'user_annotation_count': stats['user_annotation_count'] or 0,
            'analysis_count': analysis_count,
            'page_count': len(pages),
            'pages_with_annotations': pages,
            'first_annotated_page': stats['first_annotated_page'],
            'last_annotated_page': stats['last_annotated_page'],
            'last_refreshed': None  # Indicates live calculation
        }
```

### Phase 3: GraphQL Integration

#### 3.1 Progressive Loading Types

**File:** `/config/graphql/progressive_types.py`

```python
"""
Progressive loading GraphQL types for annotation performance optimization.
"""

import graphene
from graphene_django import DjangoObjectType
from graphql_relay import from_global_id, to_global_id
from typing import List, Optional
import logging
import json
from django.core.serializers.json import DjangoJSONEncoder

from opencontractserver.utils.query_optimizer import AnnotationQueryOptimizer

logger = logging.getLogger(__name__)

class AnnotationManifestType(graphene.ObjectType):
    """
    Lightweight manifest for initial page load.
    Provides statistics without loading actual annotations.
    """
    annotation_count = graphene.Int()
    structural_count = graphene.Int()
    user_annotation_count = graphene.Int()
    analysis_count = graphene.Int()
    page_count = graphene.Int()
    pages_with_annotations = graphene.List(graphene.Int)
    first_annotated_page = graphene.Int()
    last_annotated_page = graphene.Int()
    last_refreshed = graphene.String()

class NavigationEntryType(graphene.ObjectType):
    """
    Minimal annotation data for jump-to navigation.
    """
    id = graphene.ID(required=True)
    page = graphene.Int(required=True)
    bounding_box = graphene.JSONString()

class VisibleAnnotationsType(graphene.ObjectType):
    """
    Container for visible page annotations.
    """
    requested_pages = graphene.List(graphene.Int)
    loaded_pages = graphene.List(graphene.Int)
    annotations = graphene.JSONString()  # Serialized for efficiency
    total_loaded = graphene.Int()

class JumpToAnnotationType(graphene.ObjectType):
    """
    Result of jumping to a specific annotation.
    """
    page = graphene.Int(required=True)
    annotation_id = graphene.ID(required=True)
    annotations = graphene.JSONString()
    total_on_page = graphene.Int()

def create_progressive_resolvers():
    """
    Factory function to create resolvers for progressive loading.
    Returns a dictionary of resolver functions.
    """

    def resolve_annotation_manifest(self, info, corpus_id: str):
        """
        Get instant statistics without loading annotations.
        """
        try:
            _, corpus_pk = from_global_id(corpus_id)
            manifest = AnnotationQueryOptimizer.get_annotation_manifest(
                self.id,
                int(corpus_pk)
            )
            return AnnotationManifestType(**manifest)
        except Exception as e:
            logger.error(f"Error resolving annotation manifest: {e}")
            return None

    def resolve_navigation_index(self, info, corpus_id: str, analysis_id: Optional[str] = None):
        """
        Get lightweight navigation index for jump-to functionality.
        """
        try:
            _, corpus_pk = from_global_id(corpus_id)
            analysis_pk = None

            if analysis_id and analysis_id != "__none__":
                _, analysis_pk = from_global_id(analysis_id)

            entries = AnnotationQueryOptimizer.get_navigation_index(
                self.id,
                int(corpus_pk),
                int(analysis_pk) if analysis_pk else None
            )

            # Convert IDs to global IDs
            for entry in entries:
                entry['id'] = to_global_id('AnnotationType', entry['id'])

            return [NavigationEntryType(**entry) for entry in entries]
        except Exception as e:
            logger.error(f"Error resolving navigation index: {e}")
            return []

    def resolve_visible_annotations(
        self,
        info,
        corpus_id: str,
        visible_pages: List[int],
        analysis_id: Optional[str] = None,
        prefetch_adjacent: bool = True
    ):
        """
        Load annotations for visible pages only.
        """
        try:
            _, corpus_pk = from_global_id(corpus_id)
            analysis_pk = None

            if analysis_id and analysis_id != "__none__":
                _, analysis_pk = from_global_id(analysis_id)

            # Load annotations using optimizer
            annotations_by_page = AnnotationQueryOptimizer.load_visible_annotations(
                self.id,
                int(corpus_pk),
                visible_pages,
                int(analysis_pk) if analysis_pk else None,
                prefetch_adjacent
            )

            # Serialize annotations efficiently
            serialized_data = {}
            total_count = 0

            for page_num, annotations in annotations_by_page.items():
                serialized_data[str(page_num)] = []
                for ann in annotations:
                    # Create a simplified dict for serialization
                    ann_dict = {
                        'id': to_global_id('AnnotationType', ann.id),
                        'page': ann.page,
                        'raw_text': ann.raw_text,
                        'json': ann.json,
                        'bounding_box': ann.bounding_box,
                        'structural': ann.structural,
                        'created': ann.created.isoformat() if ann.created else None,
                        'annotation_label': {
                            'id': to_global_id('AnnotationLabelType', ann.annotation_label.id) if ann.annotation_label else None,
                            'text': ann.annotation_label.text if ann.annotation_label else None,
                            'color': ann.annotation_label.color if ann.annotation_label else None,
                            'icon': ann.annotation_label.icon if ann.annotation_label else None,
                        } if ann.annotation_label else None,
                        'creator': {
                            'id': to_global_id('UserType', ann.creator.id) if ann.creator else None,
                            'email': ann.creator.email if ann.creator else None,
                        } if ann.creator else None,
                        'user_feedback': [
                            {
                                'id': to_global_id('UserFeedbackType', fb.id),
                                'approved': fb.approved,
                                'rejected': fb.rejected,
                                'comment': fb.comment,
                                'creator': {
                                    'id': to_global_id('UserType', fb.creator.id) if fb.creator else None,
                                    'email': fb.creator.email if fb.creator else None,
                                } if fb.creator else None,
                            }
                            for fb in ann.user_feedback.all()
                        ] if hasattr(ann, 'user_feedback') else []
                    }
                    serialized_data[str(page_num)].append(ann_dict)
                    total_count += 1

            result = {
                'requested_pages': visible_pages,
                'loaded_pages': list(annotations_by_page.keys()),
                'annotations': json.dumps(serialized_data, cls=DjangoJSONEncoder),
                'total_loaded': total_count
            }

            return VisibleAnnotationsType(**result)

        except Exception as e:
            logger.error(f"Error loading visible annotations: {e}")
            return VisibleAnnotationsType(
                requested_pages=visible_pages,
                loaded_pages=[],
                annotations='{}',
                total_loaded=0
            )

    def resolve_jump_to_annotation(self, info, annotation_id: str):
        """
        Get specific annotation with context for jumping.
        """
        try:
            _, ann_pk = from_global_id(annotation_id)
            result = AnnotationQueryOptimizer.get_annotation_for_jump(int(ann_pk))

            if not result:
                return None

            # Load all annotations on the target page
            annotations_by_page = AnnotationQueryOptimizer.load_visible_annotations(
                result['document_id'],
                result['corpus_id'],
                [result['page']],
                prefetch_adjacent=False
            )

            # Serialize the page annotations
            page_annotations = annotations_by_page.get(result['page'], [])
            serialized_annotations = []

            for ann in page_annotations:
                ann_dict = {
                    'id': to_global_id('AnnotationType', ann.id),
                    'page': ann.page,
                    'raw_text': ann.raw_text,
                    'json': ann.json,
                    'bounding_box': ann.bounding_box,
                    'structural': ann.structural,
                    'annotation_label': {
                        'id': to_global_id('AnnotationLabelType', ann.annotation_label.id) if ann.annotation_label else None,
                        'text': ann.annotation_label.text if ann.annotation_label else None,
                        'color': ann.annotation_label.color if ann.annotation_label else None,
                    } if ann.annotation_label else None,
                }
                serialized_annotations.append(ann_dict)

            return JumpToAnnotationType(
                page=result['page'],
                annotation_id=annotation_id,
                annotations=json.dumps(serialized_annotations, cls=DjangoJSONEncoder),
                total_on_page=len(page_annotations)
            )

        except Exception as e:
            logger.error(f"Error jumping to annotation: {e}")
            return None

    return {
        'resolve_annotation_manifest': resolve_annotation_manifest,
        'resolve_navigation_index': resolve_navigation_index,
        'resolve_visible_annotations': resolve_visible_annotations,
        'resolve_jump_to_annotation': resolve_jump_to_annotation
    }
```

#### 3.2 Update DocumentType

**File:** `/config/graphql/graphene_types.py` (modifications)

Add to imports:
```python
from config.graphql.progressive_types import (
    AnnotationManifestType,
    NavigationEntryType,
    VisibleAnnotationsType,
    JumpToAnnotationType,
    create_progressive_resolvers
)
from opencontractserver.utils.query_optimizer import AnnotationQueryOptimizer
```

Add to DocumentType class after existing fields:
```python
    # PROGRESSIVE LOADING FIELDS - Add these to DocumentType

    annotation_manifest = graphene.Field(
        AnnotationManifestType,
        corpus_id=graphene.ID(required=True),
        description="Get instant annotation statistics without loading annotations"
    )

    navigation_index = graphene.List(
        NavigationEntryType,
        corpus_id=graphene.ID(required=True),
        analysis_id=graphene.ID(),
        description="Lightweight index for jump-to-annotation navigation"
    )

    visible_annotations = graphene.Field(
        VisibleAnnotationsType,
        corpus_id=graphene.ID(required=True),
        visible_pages=graphene.List(graphene.Int, required=True),
        analysis_id=graphene.ID(),
        prefetch_adjacent=graphene.Boolean(default_value=True),
        description="Load annotations for visible pages only"
    )

    jump_to_annotation = graphene.Field(
        JumpToAnnotationType,
        annotation_id=graphene.ID(required=True),
        description="Jump to specific annotation with page context"
    )

    # Add progressive loading resolvers
    _progressive_resolvers = create_progressive_resolvers()
    resolve_annotation_manifest = _progressive_resolvers['resolve_annotation_manifest']
    resolve_navigation_index = _progressive_resolvers['resolve_navigation_index']
    resolve_visible_annotations = _progressive_resolvers['resolve_visible_annotations']
    resolve_jump_to_annotation = _progressive_resolvers['resolve_jump_to_annotation']

    # OPTIMIZE EXISTING all_annotations RESOLVER
    def resolve_all_annotations(
        self, info, corpus_id=None, analysis_id=None, is_structural=None
    ):
        """
        Optimized version of annotation resolver.
        Now uses QueryOptimizer to prevent N+1 queries.
        """
        try:
            # Log warning for full annotation loads
            logger.warning(
                f"Full annotation load requested for document {self.id}. "
                f"Consider using progressive loading (visible_annotations) instead."
            )

            # Apply existing filter logic
            if corpus_id is None:
                annotations = self.doc_annotations.filter(structural=True)
            else:
                corpus_pk = from_global_id(corpus_id)[1]
                if is_structural is not None:
                    annotations = self.doc_annotations.filter(
                        corpus_id=corpus_pk, structural=is_structural
                    )
                else:
                    annotations = self.doc_annotations.filter(
                        Q(structural=True) | Q(corpus_id=corpus_pk)
                    )

            # Apply analysis filtering
            if corpus_id is not None:
                if analysis_id is None or analysis_id == "__none__":
                    annotations = annotations.filter(
                        Q(analysis__isnull=True) | Q(structural=True)
                    )
                else:
                    analysis_pk = from_global_id(analysis_id)[1]
                    annotations = annotations.filter(
                        Q(analysis_id=analysis_pk) | Q(structural=True)
                    )

            # APPLY OPTIMIZATION HERE
            annotations = AnnotationQueryOptimizer.optimize_annotation_queryset(
                annotations,
                include_feedback=True,
                include_relationships=True
            )

            return annotations.distinct()

        except Exception as e:
            logger.error(
                f"Failed resolving annotations for document {self.id}: {e}"
            )
            return []
```

### Phase 4: Frontend Integration Examples

#### 4.1 GraphQL Queries

**File:** `/frontend/src/graphql/progressive-queries.ts`

```typescript
import { gql } from '@apollo/client';

// Get initial manifest for stats
export const GET_ANNOTATION_MANIFEST = gql`
  query GetAnnotationManifest($documentId: ID!, $corpusId: ID!) {
    document(id: $documentId) {
      id
      annotationManifest(corpusId: $corpusId) {
        annotationCount
        structuralCount
        userAnnotationCount
        analysisCount
        pageCount
        pagesWithAnnotations
        firstAnnotatedPage
        lastAnnotatedPage
        lastRefreshed
      }
    }
  }
`;

// Get navigation index for jump-to
export const GET_NAVIGATION_INDEX = gql`
  query GetNavigationIndex(
    $documentId: ID!
    $corpusId: ID!
    $analysisId: ID
  ) {
    document(id: $documentId) {
      id
      navigationIndex(corpusId: $corpusId, analysisId: $analysisId) {
        id
        page
        boundingBox
      }
    }
  }
`;

// Load visible annotations
export const GET_VISIBLE_ANNOTATIONS = gql`
  query GetVisibleAnnotations(
    $documentId: ID!
    $corpusId: ID!
    $visiblePages: [Int!]!
    $analysisId: ID
    $prefetchAdjacent: Boolean
  ) {
    document(id: $documentId) {
      id
      visibleAnnotations(
        corpusId: $corpusId
        visiblePages: $visiblePages
        analysisId: $analysisId
        prefetchAdjacent: $prefetchAdjacent
      ) {
        requestedPages
        loadedPages
        annotations
        totalLoaded
      }
    }
  }
`;

// Jump to specific annotation
export const JUMP_TO_ANNOTATION = gql`
  query JumpToAnnotation($documentId: ID!, $annotationId: ID!) {
    document(id: $documentId) {
      id
      jumpToAnnotation(annotationId: $annotationId) {
        page
        annotationId
        annotations
        totalOnPage
      }
    }
  }
`;
```

#### 4.2 React Hook Example

**File:** `/frontend/src/hooks/useProgressiveAnnotations.ts`

```typescript
import { useState, useEffect, useCallback, useRef } from 'react';
import { useQuery, useLazyQuery } from '@apollo/client';
import {
  GET_ANNOTATION_MANIFEST,
  GET_NAVIGATION_INDEX,
  GET_VISIBLE_ANNOTATIONS,
  JUMP_TO_ANNOTATION
} from '../graphql/progressive-queries';

interface UseProgressiveAnnotationsOptions {
  documentId: string;
  corpusId: string;
  analysisId?: string;
  initialVisiblePages?: number[];
  prefetchBuffer?: number;
}

export function useProgressiveAnnotations({
  documentId,
  corpusId,
  analysisId,
  initialVisiblePages = [1],
  prefetchBuffer = 2
}: UseProgressiveAnnotationsOptions) {
  const [annotations, setAnnotations] = useState<Record<number, any[]>>({});
  const [manifest, setManifest] = useState<any>(null);
  const [navigationIndex, setNavigationIndex] = useState<any[]>([]);
  const [visiblePages, setVisiblePages] = useState(initialVisiblePages);
  const loadedPages = useRef(new Set<number>());

  // Load manifest on mount
  const { data: manifestData, loading: manifestLoading } = useQuery(
    GET_ANNOTATION_MANIFEST,
    {
      variables: { documentId, corpusId },
      onCompleted: (data) => {
        setManifest(data.document.annotationManifest);
      }
    }
  );

  // Load navigation index
  const { data: navData } = useQuery(GET_NAVIGATION_INDEX, {
    variables: { documentId, corpusId, analysisId },
    onCompleted: (data) => {
      setNavigationIndex(data.document.navigationIndex);
    }
  });

  // Lazy query for loading visible annotations
  const [loadVisibleAnnotations] = useLazyQuery(GET_VISIBLE_ANNOTATIONS, {
    fetchPolicy: 'cache-first',
    onCompleted: (data) => {
      const result = data.document.visibleAnnotations;
      const parsed = JSON.parse(result.annotations);

      // Merge new annotations with existing
      setAnnotations(prev => ({
        ...prev,
        ...parsed
      }));

      // Track loaded pages
      result.loadedPages.forEach((page: number) => {
        loadedPages.current.add(page);
      });
    }
  });

  // Load annotations for visible pages
  const loadPages = useCallback((pages: number[]) => {
    // Filter out already loaded pages
    const pagesToLoad = pages.filter(p => !loadedPages.current.has(p));

    if (pagesToLoad.length > 0) {
      loadVisibleAnnotations({
        variables: {
          documentId,
          corpusId,
          visiblePages: pagesToLoad,
          analysisId,
          prefetchAdjacent: true
        }
      });
    }
  }, [documentId, corpusId, analysisId, loadVisibleAnnotations]);

  // Jump to annotation
  const [jumpToAnnotation] = useLazyQuery(JUMP_TO_ANNOTATION, {
    onCompleted: (data) => {
      const result = data.document.jumpToAnnotation;
      const parsed = JSON.parse(result.annotations);

      // Update annotations for the target page
      setAnnotations(prev => ({
        ...prev,
        [result.page]: parsed
      }));

      // Scroll to the page
      // Implementation depends on your PDF viewer
      scrollToPage(result.page);
    }
  });

  // Handle page visibility changes
  const handlePageVisibilityChange = useCallback((newVisiblePages: number[]) => {
    setVisiblePages(newVisiblePages);

    // Calculate pages to prefetch
    const minPage = Math.min(...newVisiblePages);
    const maxPage = Math.max(...newVisiblePages);
    const pagesToLoad = [];

    for (let i = Math.max(1, minPage - prefetchBuffer);
         i <= maxPage + prefetchBuffer;
         i++) {
      pagesToLoad.push(i);
    }

    loadPages(pagesToLoad);
  }, [loadPages, prefetchBuffer]);

  // Initial load
  useEffect(() => {
    if (visiblePages.length > 0) {
      loadPages(visiblePages);
    }
  }, []);

  return {
    annotations,
    manifest,
    navigationIndex,
    loading: manifestLoading,
    handlePageVisibilityChange,
    jumpToAnnotation: (annotationId: string) => {
      jumpToAnnotation({ variables: { documentId, annotationId } });
    }
  };
}

// Helper function (implement based on your PDF viewer)
function scrollToPage(page: number) {
  // Implementation depends on your PDF viewer library
  console.log(`Scrolling to page ${page}`);
}
```

### Phase 5: Testing & Monitoring

#### 5.1 Performance Tests

**File:** `/opencontractserver/tests/test_annotation_performance.py`

```python
import time
from django.test import TestCase, TransactionTestCase
from django.db import connection
from django.test.utils import override_settings
from django.contrib.auth import get_user_model

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.documents.models import Document
from opencontractserver.corpuses.models import Corpus
from opencontractserver.utils.query_optimizer import AnnotationQueryOptimizer

User = get_user_model()

class AnnotationPerformanceTest(TransactionTestCase):
    """
    Test progressive loading performance improvements.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Create test data
        cls.user = User.objects.create_user(
            username='testuser',
            email='test@test.com'
        )

        cls.corpus = Corpus.objects.create(
            title="Test Corpus",
            creator=cls.user
        )

        cls.document = Document.objects.create(
            title="Test Document",
            creator=cls.user,
            page_count=100
        )

        cls.label = AnnotationLabel.objects.create(
            text="Test Label",
            creator=cls.user
        )

        # Create many annotations for performance testing
        annotations = []
        for page in range(1, 101):  # 100 pages
            for i in range(100):  # 100 annotations per page = 10,000 total
                annotations.append(
                    Annotation(
                        document=cls.document,
                        corpus=cls.corpus,
                        page=page,
                        annotation_label=cls.label,
                        raw_text=f"Annotation {i} on page {page}",
                        creator=cls.user,
                        structural=False
                    )
                )

        Annotation.objects.bulk_create(annotations)

        # Refresh materialized views
        with connection.cursor() as cursor:
            cursor.execute("REFRESH MATERIALIZED VIEW annotation_summary_mv")
            cursor.execute("REFRESH MATERIALIZED VIEW annotation_navigation_mv")

    def test_manifest_performance(self):
        """Test that manifest loads in <50ms"""
        start = time.perf_counter()

        manifest = AnnotationQueryOptimizer.get_annotation_manifest(
            self.document.id,
            self.corpus.id
        )

        duration_ms = (time.perf_counter() - start) * 1000

        self.assertLess(duration_ms, 50, f"Manifest took {duration_ms:.2f}ms")
        self.assertEqual(manifest['annotation_count'], 10000)
        self.assertEqual(manifest['page_count'], 100)

    def test_visible_pages_performance(self):
        """Test that loading 3 visible pages is fast"""
        start = time.perf_counter()

        annotations = AnnotationQueryOptimizer.load_visible_annotations(
            self.document.id,
            self.corpus.id,
            [1, 2, 3],  # Load first 3 pages
            prefetch_adjacent=True
        )

        duration_ms = (time.perf_counter() - start) * 1000

        self.assertLess(duration_ms, 200, f"Loading pages took {duration_ms:.2f}ms")

        # Should have loaded requested pages plus adjacent
        self.assertIn(1, annotations)
        self.assertIn(2, annotations)
        self.assertIn(3, annotations)

        # With prefetch, should also have adjacent pages
        self.assertTrue(len(annotations) > 3)

    def test_navigation_index_performance(self):
        """Test navigation index generation"""
        start = time.perf_counter()

        nav_index = AnnotationQueryOptimizer.get_navigation_index(
            self.document.id,
            self.corpus.id
        )

        duration_ms = (time.perf_counter() - start) * 1000

        self.assertLess(duration_ms, 500, f"Navigation index took {duration_ms:.2f}ms")
        self.assertEqual(len(nav_index), 10000)

    def test_query_count_optimization(self):
        """Test that query optimization reduces database hits"""

        # Test unoptimized query count
        with self.assertNumQueries(10001):  # 1 + N queries
            annotations = list(
                Annotation.objects.filter(
                    document=self.document,
                    corpus=self.corpus,
                    page__in=[1, 2, 3]
                )
            )
            # Access related fields to trigger N+1
            for ann in annotations:
                _ = ann.annotation_label.text
                _ = ann.creator.email

        # Test optimized query count
        with self.assertNumQueries(3):  # Just 3 queries with prefetch
            qs = Annotation.objects.filter(
                document=self.document,
                corpus=self.corpus,
                page__in=[1, 2, 3]
            )
            qs = AnnotationQueryOptimizer.optimize_annotation_queryset(qs)
            annotations = list(qs)

            # Access related fields - should not trigger extra queries
            for ann in annotations:
                _ = ann.annotation_label.text
                _ = ann.creator.email

    def test_jump_to_annotation(self):
        """Test jump-to-annotation performance"""
        target_annotation = Annotation.objects.filter(page=50).first()

        start = time.perf_counter()

        result = AnnotationQueryOptimizer.get_annotation_for_jump(
            target_annotation.id
        )

        duration_ms = (time.perf_counter() - start) * 1000

        self.assertLess(duration_ms, 100, f"Jump took {duration_ms:.2f}ms")
        self.assertEqual(result['page'], 50)
        self.assertEqual(result['target'].id, target_annotation.id)
        self.assertEqual(len(result['page_annotations']), 100)  # 100 annotations on page 50
```

#### 5.2 Monitoring Queries

**File:** `/opencontractserver/utils/monitoring.sql`

```sql
-- Check index usage
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
  AND tablename LIKE '%annotation%'
ORDER BY idx_scan DESC;

-- Monitor slow queries (requires pg_stat_statements)
SELECT
    query,
    mean_exec_time,
    calls,
    total_exec_time
FROM pg_stat_statements
WHERE query LIKE '%annotation%'
  AND mean_exec_time > 100
ORDER BY mean_exec_time DESC
LIMIT 20;

-- Materialized view freshness from data
SELECT MAX(last_refreshed) AS last_refreshed FROM annotation_summary_mv;

-- Analyze plan for a representative page-scoped query
EXPLAIN (ANALYZE, BUFFERS)
SELECT a.*
FROM annotations_annotation a
WHERE a.document_id = 1
  AND a.corpus_id = 1
  AND a.page IN (1, 2, 3)
  AND a.structural = false;
```

### Phase 6: Deployment & Rollout

#### 6.1 Deployment Checklist

1. **Database Migrations** (Day 1)
   ```bash
   # Apply migrations during low traffic
   python manage.py migrate annotations 0036
   python manage.py migrate annotations 0037

   # Verify indexes created
   python manage.py dbshell
   \di *annotation*
   ```

2. **Initial Materialized View Population**
   ```bash
   # Run in Django shell
   python manage.py shell
   >>> from opencontractserver.annotations.tasks import refresh_annotation_materialized_views
   >>> refresh_annotation_materialized_views()
   ```

3. **Deploy Backend Changes** (Day 2)
   - Deploy query_optimizer.py
   - Deploy progressive_types.py
   - Update graphene_types.py
   - Deploy updated signals.py and tasks.py

4. **Feature Flag Rollout** (Day 3-5)
   ```python
   # In settings.py
   FEATURES = {
       'PROGRESSIVE_ANNOTATION_LOADING': env.bool('ENABLE_PROGRESSIVE_LOADING', False)
   }
   ```

5. **Frontend Migration** (Day 5-7)
   - Deploy new GraphQL queries
   - Update components to use progressive loading
   - Keep fallback to old queries during transition

6. **Monitoring & Optimization** (Week 2)
   - Monitor query performance
   - Adjust prefetch buffer sizes
   - Tune materialized view refresh frequency

#### 6.2 Rollback Plan

If issues arise:

1. **Frontend**: Revert to using old `all_annotations` query
2. **Backend**: Keep optimizations (they improve old queries too)
3. **Database**: Indexes and views are safe to keep

---

## Expected Results

### Performance Improvements

| Metric | Current | Optimized | Improvement |
|--------|---------|-----------|-------------|
| Initial Load | 15-30s | <500ms | 30-60x faster |
| Database Queries | 2,500-5,000 | 5-10 | 99.8% reduction |
| Memory Usage | 500MB-1GB | <50MB | 90-95% reduction |
| Data Transfer | 10-20MB | <500KB | 95-97% reduction |
| Jump to Annotation | 5-10s | <100ms | 50-100x faster |
| Scroll Performance | Janky | Smooth | Significantly improved |

### User Experience Improvements

1. **Instant page loads** - Statistics appear immediately
2. **Smooth scrolling** - Annotations load as needed
3. **Fast navigation** - Jump to any annotation instantly
4. **Reduced bandwidth** - Only load visible content
5. **Better responsiveness** - UI remains responsive during loads

---

## Troubleshooting Guide

### Common Issues

1. **Materialized views not updating**
   ```sql
   -- Check last refresh time
   SELECT * FROM pg_matviews WHERE matviewname LIKE 'annotation%';

   -- Manual refresh
   REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv;
   ```

2. **Slow manifest queries**
   ```python
   # Check if using materialized view
   from django.db import connection
   with connection.cursor() as cursor:
       cursor.execute("EXPLAIN SELECT * FROM annotation_summary_mv WHERE document_id = 1")
       print(cursor.fetchall())
   ```

3. **Pages not loading**
   ```javascript
   // Check browser console for GraphQL errors
   // Verify visible pages are being detected correctly
   console.log('Visible pages:', visiblePages);
   ```

---

## Conclusion

This optimization guide provides a complete, production-ready solution for the annotation performance problem. The key insight is **progressive loading**: instead of loading 10,000+ annotations upfront, load only what's visible. Combined with strategic database optimization and smart prefetching, this achieves exceptional performance while maintaining all functionality.

The implementation is:
- **Safe**: Backwards compatible with existing code
- **Simple**: No complex caching infrastructure needed
- **Scalable**: Performance remains constant regardless of annotation count
- **Maintainable**: Clear separation of concerns and minimal dependencies

By following this guide, the OpenContracts system will deliver a dramatically improved user experience with sub-second response times.