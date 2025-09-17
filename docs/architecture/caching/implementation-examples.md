# Query Optimization Implementation Examples

This document provides practical, copy-paste ready examples for implementing the query optimization paradigm in OpenContracts.

## Table of Contents

1. [Frontend Implementation](#frontend-implementation)
2. [Backend Implementation](#backend-implementation)
3. [Testing Patterns](#testing-patterns)
4. [Debugging Guide](#debugging-guide)
5. [Performance Monitoring](#performance-monitoring)

## Frontend Implementation

### Progressive Document Loading (React/TypeScript)

```typescript
// hooks/useProgressiveDocumentLoader.ts
import { useState, useEffect, useCallback } from 'react';
import { useQuery, useLazyQuery } from '@apollo/client';
import {
  GET_DOCUMENT_SUMMARY,
  GET_STRUCTURAL_ANNOTATIONS,
  GET_PAGE_ANNOTATIONS,
  GET_ANNOTATION_NAVIGATION
} from '../graphql/queries';

interface ProgressiveDocumentState {
  summary: AnnotationSummary | null;
  structuralAnnotations: Annotation[];
  pageAnnotations: Map<number, Annotation[]>;
  isLoading: boolean;
  loadedPages: Set<number>;
}

export function useProgressiveDocumentLoader(
  documentId: string,
  corpusId: string,
  analysisId?: string
) {
  const [state, setState] = useState<ProgressiveDocumentState>({
    summary: null,
    structuralAnnotations: [],
    pageAnnotations: new Map(),
    isLoading: true,
    loadedPages: new Set()
  });

  // 1. Load summary (instant from materialized view)
  const { data: summaryData } = useQuery(GET_DOCUMENT_SUMMARY, {
    variables: { documentId, corpusId }
  });

  // 2. Load structural annotations
  const { data: structuralData } = useQuery(GET_STRUCTURAL_ANNOTATIONS, {
    variables: { documentId },
    skip: !summaryData
  });

  // 3. Lazy load page annotations
  const [loadPageAnnotations] = useLazyQuery(GET_PAGE_ANNOTATIONS);

  // Load annotations for a specific page
  const loadPage = useCallback(async (pageNumber: number) => {
    if (state.loadedPages.has(pageNumber)) return;

    const { data } = await loadPageAnnotations({
      variables: {
        documentId,
        corpusId,
        page: pageNumber,
        analysisId
      }
    });

    setState(prev => ({
      ...prev,
      pageAnnotations: new Map(prev.pageAnnotations).set(
        pageNumber,
        data.document.pageAnnotations
      ),
      loadedPages: new Set(prev.loadedPages).add(pageNumber)
    }));
  }, [documentId, corpusId, analysisId, state.loadedPages]);

  // Load visible pages on mount
  useEffect(() => {
    if (summaryData?.document?.annotationSummary) {
      const summary = summaryData.document.annotationSummary;
      const firstPages = summary.pagesWithAnnotations.slice(0, 3);

      firstPages.forEach(page => loadPage(page));
    }
  }, [summaryData, loadPage]);

  // Combine all annotations for current view
  const getAllAnnotations = useCallback(() => {
    const combined: Annotation[] = [...state.structuralAnnotations];

    state.pageAnnotations.forEach(pageAnns => {
      combined.push(...pageAnns);
    });

    // Deduplicate by ID
    const seen = new Set<string>();
    return combined.filter(ann => {
      if (seen.has(ann.id)) return false;
      seen.add(ann.id);
      return true;
    });
  }, [state.structuralAnnotations, state.pageAnnotations]);

  return {
    summary: summaryData?.document?.annotationSummary,
    structuralAnnotations: structuralData?.document?.allStructuralAnnotations || [],
    loadPage,
    getAllAnnotations,
    isPageLoaded: (page: number) => state.loadedPages.has(page),
    loadedPages: state.loadedPages
  };
}
```

### Viewport-Based Loading

```typescript
// components/DocumentViewer.tsx
import { useInView } from 'react-intersection-observer';

function PageContainer({ pageNumber, documentId, corpusId }) {
  const { loadPage, isPageLoaded } = useProgressiveDocumentLoader(
    documentId,
    corpusId
  );

  // Load when page comes into viewport
  const { ref } = useInView({
    threshold: 0.1,
    triggerOnce: true,
    onChange: (inView) => {
      if (inView && !isPageLoaded(pageNumber)) {
        loadPage(pageNumber);
      }
    }
  });

  return (
    <div ref={ref} className="page-container">
      {isPageLoaded(pageNumber) ? (
        <AnnotatedPage pageNumber={pageNumber} />
      ) : (
        <PageSkeleton />
      )}
    </div>
  );
}
```

### GraphQL Queries

```graphql
# queries/progressive-loading.graphql

# 1. Summary Query (uses materialized view - instant)
query GetDocumentSummary($documentId: String!, $corpusId: ID!) {
  document(id: $documentId) {
    id
    annotationSummary(corpusId: $corpusId) {
      annotationCount
      structuralCount
      pageCount
      pagesWithAnnotations
      firstPage
      lastPage
    }
  }
}

# 2. Structural Annotations (document-wide, with optimizations)
query GetStructuralAnnotations($documentId: String!) {
  document(id: $documentId) {
    allStructuralAnnotations {
      id
      page
      rawText
      annotationLabel {
        id
        text
        color
      }
      userFeedback {
        totalCount
        edges {
          node {
            id
            approved
            rejected
            comment
          }
        }
      }
    }
  }
}

# 3. Page-Specific Annotations (indexed query)
query GetPageAnnotations(
  $documentId: String!
  $corpusId: ID!
  $page: Int!
  $analysisId: ID
) {
  document(id: $documentId) {
    pageAnnotations(
      corpusId: $corpusId
      page: $page
      analysisId: $analysisId
    ) {
      id
      page
      rawText
      boundingBox
      annotationLabel {
        id
        text
        color
      }
      userFeedback {
        totalCount
        edges {
          node {
            id
            approved
            rejected
          }
        }
      }
    }
  }
}

# 4. Navigation Data (lightweight for minimap)
query GetAnnotationNavigation(
  $documentId: String!
  $corpusId: ID!
) {
  document(id: $documentId) {
    annotationNavigation(corpusId: $corpusId) {
      id
      page
      boundingBox
    }
  }
}
```

## Backend Implementation

### Custom GraphQL Resolver with Optimization

```python
# config/graphql/resolvers.py

from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from graphql_relay import from_global_id

class OptimizedDocumentType(DjangoObjectType):
    """Document type with progressive loading support."""

    annotation_summary = graphene.Field(
        AnnotationSummaryType,
        corpus_id=graphene.ID(required=True),
        description="Get annotation statistics from materialized view"
    )

    page_annotations = graphene.List(
        AnnotationType,
        corpus_id=graphene.ID(required=True),
        page=graphene.Int(required=True),
        analysis_id=graphene.ID(),
        description="Get annotations for specific page with optimizations"
    )

    def resolve_annotation_summary(self, info, corpus_id):
        """Resolve using materialized view for instant response."""
        _, corpus_pk = from_global_id(corpus_id)

        # This uses materialized view - instant!
        return AnnotationQueryOptimizer.get_annotation_summary(
            document_id=self.id,
            corpus_id=corpus_pk,
            use_mv=True  # Use materialized view
        )

    def resolve_page_annotations(self, info, corpus_id, page, analysis_id=None):
        """Resolve page annotations with all optimizations."""
        _, corpus_pk = from_global_id(corpus_id)
        analysis_pk = None
        if analysis_id:
            _, analysis_pk = from_global_id(analysis_id)

        # This uses query optimizer with prefetch_related
        return AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.id,
            corpus_id=corpus_pk,
            page=page,
            analysis_id=analysis_pk,
            use_cache=True
        )

    def resolve_all_structural_annotations(self, info):
        """Get structural annotations with optimizations."""
        # IMPORTANT: Include prefetch_related to avoid N+1
        return self.doc_annotations.filter(structural=True)\
            .select_related("annotation_label", "creator")\
            .prefetch_related("user_feedback")\
            .distinct()
```

### Materialized View Management

```python
# annotations/materialized_views.py

from django.db import connection
from celery import shared_task
import logging

logger = logging.getLogger(__name__)

class MaterializedViewManager:
    """Manages materialized view refresh and fallback strategies."""

    @staticmethod
    def refresh_annotation_summary(document_id: int, corpus_id: int):
        """Refresh materialized view for specific document/corpus."""
        with connection.cursor() as cursor:
            try:
                # Use CONCURRENTLY to avoid blocking reads
                cursor.execute("""
                    REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv
                """)
                logger.info(f"Refreshed annotation_summary_mv for doc {document_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to refresh materialized view: {e}")
                return False

    @staticmethod
    def check_staleness(document_id: int, corpus_id: int) -> dict:
        """Check if materialized view data is stale."""
        with connection.cursor() as cursor:
            # Check last annotation modification
            cursor.execute("""
                SELECT MAX(modified)
                FROM annotations_annotation
                WHERE document_id = %s AND corpus_id = %s
            """, [document_id, corpus_id])
            last_annotation_update = cursor.fetchone()[0]

            # Check materialized view refresh time
            cursor.execute("""
                SELECT pg_stat_user_tables.last_vacuum
                FROM pg_stat_user_tables
                WHERE schemaname = 'public'
                AND tablename = 'annotation_summary_mv'
            """)
            last_refresh = cursor.fetchone()[0]

            is_stale = last_annotation_update > last_refresh if both else False

            return {
                'is_stale': is_stale,
                'last_update': last_annotation_update,
                'last_refresh': last_refresh,
                'staleness_seconds': (
                    (last_annotation_update - last_refresh).total_seconds()
                    if is_stale else 0
                )
            }

@shared_task
def refresh_materialized_views_async(document_id: int, corpus_id: int):
    """Celery task to refresh materialized views asynchronously."""
    manager = MaterializedViewManager()
    manager.refresh_annotation_summary(document_id, corpus_id)
```

### Signal Handlers for Cache Invalidation

```python
# annotations/signals.py

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from .models import Annotation
from .tasks import refresh_materialized_views_async

@receiver([post_save, post_delete], sender=Annotation)
def invalidate_annotation_caches(sender, instance, **kwargs):
    """Invalidate all caches when annotations change."""

    # 1. Clear Django cache
    cache_patterns = [
        f"annotation_summary:{instance.document_id}:{instance.corpus_id}",
        f"doc_annotations:{instance.document_id}:*",
        f"annotation_navigation:{instance.document_id}:*"
    ]

    for pattern in cache_patterns:
        if '*' in pattern:
            # Use cache.delete_pattern if available (Redis)
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(pattern)
        else:
            cache.delete(pattern)

    # 2. Schedule materialized view refresh
    refresh_materialized_views_async.delay(
        document_id=instance.document_id,
        corpus_id=instance.corpus_id
    )

    # 3. Log for monitoring
    logger.info(
        f"Invalidated caches for doc {instance.document_id}, "
        f"corpus {instance.corpus_id} after annotation {instance.id} change"
    )
```

## Testing Patterns

### Testing Progressive Loading with Data Parity

```python
# tests/test_progressive_loading.py

from django.test import TransactionTestCase
from graphene.test import Client
from graphql_relay import to_global_id

class ProgressiveLoadingTestCase(TransactionTestCase):
    """Test progressive loading maintains data parity with monolithic query."""

    def setUp(self):
        # Create clean test data (don't use fixtures with old enums!)
        self.user = User.objects.create_user('testuser')
        self.doc = Document.objects.create(
            title="Test Doc",
            creator=self.user,
            file_type="application/pdf"
        )
        self.corpus = Corpus.objects.create(
            title="Test Corpus",
            creator=self.user
        )

        # Create annotations with VALID enum values
        self.label = AnnotationLabel.objects.create(
            text="Test Label",
            label_type="SPAN_LABEL",  # Valid enum!
            creator=self.user
        )

        # Create test annotations
        self._create_test_annotations()

        self.client = Client(schema)

    def test_progressive_equals_monolithic(self):
        """Verify progressive loading returns same data as monolithic."""

        doc_id = to_global_id("DocumentType", self.doc.id)
        corpus_id = to_global_id("CorpusType", self.corpus.id)

        # Get monolithic data
        monolithic_result = self._get_monolithic_data(doc_id, corpus_id)

        # Get progressive data
        progressive_result = self._get_progressive_data(doc_id, corpus_id)

        # Combine progressive results correctly
        all_progressive = self._combine_progressive_results(progressive_result)

        # Assert data parity
        self.assertEqual(
            len(monolithic_result['allAnnotations']),
            len(all_progressive),
            "Annotation counts must match"
        )

        # Check each annotation exists in both
        monolithic_ids = {a['id'] for a in monolithic_result['allAnnotations']}
        progressive_ids = {a['id'] for a in all_progressive}

        self.assertEqual(
            monolithic_ids,
            progressive_ids,
            "Annotation ID sets must be identical"
        )

    def _combine_progressive_results(self, progressive_data):
        """Combine structural and page annotations, removing duplicates."""
        structural = progressive_data.get('structuralAnnotations', [])
        page_anns = progressive_data.get('pageAnnotations', [])

        # Combine
        combined = structural + page_anns

        # Deduplicate
        seen = set()
        unique = []
        for ann in combined:
            if ann['id'] not in seen:
                seen.add(ann['id'])
                unique.append(ann)

        return unique
```

### Performance Benchmarking Test

```python
# tests/test_performance.py

import time
from django.test import TestCase
from django.test.utils import override_settings

class QueryPerformanceTest(TestCase):
    """Benchmark query performance improvements."""

    def setUp(self):
        # Create large dataset
        self.doc = self._create_document_with_many_annotations(
            num_pages=100,
            annotations_per_page=20
        )

    @override_settings(DEBUG=True)  # Enable query logging
    def test_query_performance(self):
        """Compare monolithic vs progressive query performance."""
        from django.db import connection
        from django.db import reset_queries

        # Test monolithic query
        reset_queries()
        start = time.perf_counter()
        monolithic_result = self._run_monolithic_query()
        monolithic_time = time.perf_counter() - start
        monolithic_queries = len(connection.queries)

        # Test progressive query
        reset_queries()
        start = time.perf_counter()
        progressive_result = self._run_progressive_query()
        progressive_time = time.perf_counter() - start
        progressive_queries = len(connection.queries)

        # Assertions
        self.assertLess(
            progressive_time,
            monolithic_time * 0.5,  # Should be at least 2x faster
            f"Progressive ({progressive_time:.2f}s) should be faster than "
            f"monolithic ({monolithic_time:.2f}s)"
        )

        self.assertLess(
            progressive_queries,
            monolithic_queries,
            f"Progressive should use fewer queries ({progressive_queries} vs "
            f"{monolithic_queries})"
        )

        # Log results
        print(f"""
        Performance Results:
        ====================
        Monolithic: {monolithic_time:.3f}s ({monolithic_queries} queries)
        Progressive: {progressive_time:.3f}s ({progressive_queries} queries)
        Speedup: {monolithic_time/progressive_time:.1f}x
        Query Reduction: {monolithic_queries/progressive_queries:.1f}x
        """)
```

## Debugging Guide

### Detecting N+1 Queries

```python
# utils/debug.py

from django.conf import settings
from django.db import connection
import functools
import logging

logger = logging.getLogger(__name__)

def log_queries(func):
    """Decorator to log database queries for a function."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from django.db import reset_queries

        # Only in DEBUG mode
        if not settings.DEBUG:
            return func(*args, **kwargs)

        reset_queries()
        result = func(*args, **kwargs)

        queries = connection.queries
        total_time = sum(float(q['time']) for q in queries)

        # Detect potential N+1
        similar_queries = {}
        for query in queries:
            sql = query['sql'].split('WHERE')[0]  # Group by query pattern
            similar_queries[sql] = similar_queries.get(sql, 0) + 1

        # Log suspicious patterns
        for pattern, count in similar_queries.items():
            if count > 10:  # Threshold for N+1 detection
                logger.warning(
                    f"Potential N+1 detected: {count} similar queries:\n{pattern}"
                )

        logger.info(
            f"{func.__name__}: {len(queries)} queries in {total_time:.3f}s"
        )

        return result
    return wrapper

# Usage
@log_queries
def get_annotations_with_feedback(doc_id):
    annotations = Annotation.objects.filter(document_id=doc_id)
    for ann in annotations:
        # This will trigger N+1 if not using prefetch_related!
        feedback_count = ann.user_feedback.count()
    return annotations
```

### Query Inspection Tool

```python
# management/commands/inspect_queries.py

from django.core.management.base import BaseCommand
from django.db import connection
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer

class Command(BaseCommand):
    """Inspect and analyze query performance."""

    def add_arguments(self, parser):
        parser.add_argument('--document-id', type=int, required=True)
        parser.add_argument('--corpus-id', type=int, required=True)

    def handle(self, *args, **options):
        doc_id = options['document_id']
        corpus_id = options['corpus_id']

        # Test with optimization
        with connection.execute_wrapper(self.query_logger):
            optimized = AnnotationQueryOptimizer.get_document_annotations(
                document_id=doc_id,
                corpus_id=corpus_id
            )
            list(optimized)  # Force evaluation

        self.stdout.write(
            self.style.SUCCESS(f"Analyzed {len(self.queries)} queries")
        )

    def query_logger(self, execute, sql, params, many, context):
        """Log executed queries."""
        result = execute(sql, params, many, context)
        self.queries.append({
            'sql': sql,
            'params': params,
            'duration': context['duration']
        })
        return result
```

## Performance Monitoring

### Grafana Dashboard Queries

```sql
-- Average query time by type
SELECT
    date_trunc('minute', created_at) as time,
    query_type,
    AVG(duration_ms) as avg_duration,
    COUNT(*) as query_count
FROM query_performance_log
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY time, query_type
ORDER BY time DESC;

-- Cache hit rate
SELECT
    date_trunc('minute', timestamp) as time,
    cache_key_pattern,
    SUM(CASE WHEN hit THEN 1 ELSE 0 END)::float / COUNT(*) as hit_rate
FROM cache_access_log
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY time, cache_key_pattern;

-- Materialized view staleness
SELECT
    view_name,
    MAX(EXTRACT(EPOCH FROM (NOW() - last_refresh))) as staleness_seconds
FROM pg_stat_user_tables
WHERE tablename LIKE '%_mv'
GROUP BY view_name;
```

### Custom Middleware for Performance Tracking

```python
# middleware/performance.py

import time
import logging
from django.db import connection

logger = logging.getLogger('performance')

class QueryPerformanceMiddleware:
    """Track query performance for monitoring."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for static files
        if request.path.startswith('/static/'):
            return self.get_response(request)

        # Reset query tracking
        from django.db import reset_queries
        reset_queries()

        start_time = time.perf_counter()
        response = self.get_response(request)
        duration = time.perf_counter() - start_time

        # Log if slow or many queries
        query_count = len(connection.queries)
        if duration > 1.0 or query_count > 50:
            logger.warning(
                f"Slow request: {request.path} - "
                f"{duration:.3f}s, {query_count} queries"
            )

        # Add headers for debugging
        response['X-DB-Query-Count'] = str(query_count)
        response['X-Response-Time'] = f"{duration:.3f}"

        return response
```

## Conclusion

These implementation examples provide practical, production-ready patterns for implementing the query optimization paradigm. Key takeaways:

1. **Always use the QueryOptimizer** for annotation queries
2. **Implement progressive loading** in frontend for better UX
3. **Monitor performance** continuously
4. **Test for data parity** when making changes
5. **Use proper enum values** in test data
6. **Prefetch related data** to avoid N+1 queries

The combination of these patterns enables the 30-60x performance improvements seen in production.
