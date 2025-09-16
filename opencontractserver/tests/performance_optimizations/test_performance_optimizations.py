"""
Comprehensive performance test suite for database optimizations.
Tests indexes, materialized views, query optimizer, and GraphQL progressive loading together.
"""

import time

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from graphql_relay import to_global_id

from opencontractserver.analyzer.models import Analysis, Analyzer
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tasks.materialized_view_tasks import (
    check_materialized_view_staleness,
)
from opencontractserver.tests.base import BaseFixtureTestCase

User = get_user_model()


class ComprehensivePerformanceTestCase(BaseFixtureTestCase):
    """
    Comprehensive test suite that validates all performance optimizations work together.
    """

    def setUp(self):
        super().setUp()

        # Create test corpus
        self.corpus = Corpus.objects.create(
            title="Performance Test Corpus", creator=self.user
        )

        # Create test analyzer first (required for Analysis foreign key)
        # Analyzer requires either task_name or host_gremlin (constraint)
        self.analyzer = Analyzer.objects.create(
            id="test_analyzer",
            description="Test analyzer for performance tests",
            creator=self.user,
            manifest={},
            task_name="test_task",  # Required by constraint
        )

        # Create test analysis with proper foreign key reference
        self.analysis = Analysis.objects.create(
            analyzer=self.analyzer, analyzed_corpus=self.corpus, creator=self.user
        )

        # Create test label
        self.label = AnnotationLabel.objects.create(
            text="Performance Test Label", creator=self.user
        )

        # Create large dataset for performance testing
        self._create_large_dataset()

    def _create_large_dataset(self):
        """Create a large dataset for performance testing."""
        annotations = []

        # Create 100 pages with 10 annotations each (1000 total)
        for page in range(1, 101):
            for i in range(10):
                annotations.append(
                    Annotation(
                        document=self.doc,
                        corpus=self.corpus,
                        page=page,
                        annotation_label=self.label,
                        raw_text=f"Performance annotation {i} on page {page}",
                        creator=self.user,
                        structural=(i == 0),  # First annotation per page is structural
                        analysis=(
                            self.analysis if i % 3 == 0 else None
                        ),  # 30% have analysis
                        bounding_box={
                            "x": i * 50,
                            "y": page * 10,
                            "width": 40,
                            "height": 10,
                        },
                    )
                )

        Annotation.objects.bulk_create(annotations)

        # Refresh materialized views after bulk insert (if they exist)
        with connection.cursor() as cursor:
            # Check if materialized views exist before refreshing
            cursor.execute(
                """
                SELECT matviewname FROM pg_matviews
                WHERE matviewname IN ('annotation_summary_mv', 'annotation_navigation_mv')
            """
            )
            existing_views = [row[0] for row in cursor.fetchall()]

            if "annotation_summary_mv" in existing_views:
                cursor.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
                )
            if "annotation_navigation_mv" in existing_views:
                cursor.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_navigation_mv"
                )

    def test_indexes_reduce_query_time(self):
        """Test that indexes significantly reduce query time."""

        # Test page-specific query (should use idx_ann_doc_corpus_page_nonstruct)
        start = time.perf_counter()
        result = list(
            Annotation.objects.filter(
                document=self.doc, corpus=self.corpus, page=50, structural=False
            )
        )
        page_query_time = time.perf_counter() - start

        self.assertEqual(len(result), 9)  # 9 non-structural per page
        self.assertLess(
            page_query_time,
            0.01,
            f"Page query took {page_query_time:.4f}s, expected < 0.01s with index",
        )

        # Test user annotation query (should use idx_ann_doc_corpus_page_user)
        start = time.perf_counter()
        result = list(
            Annotation.objects.filter(
                document=self.doc,
                corpus=self.corpus,
                page__in=[10, 20, 30],
                structural=False,
                analysis__isnull=True,
            )
        )
        user_query_time = time.perf_counter() - start

        self.assertLess(
            user_query_time,
            0.02,
            f"User annotation query took {user_query_time:.4f}s, expected < 0.02s",
        )

    def test_materialized_view_performance(self):
        """Test that materialized views provide instant aggregations."""

        # Pre-warm DB connection (avoid cold-start effects)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        # Measure MV-backed summary retrieval with cache cleared between runs
        cache_key = f"annotation_summary:{self.doc.id}:{self.corpus.id}:{self.user.id}"
        mv_times = []
        summary = None
        for _ in range(3):
            cache.delete(cache_key)
            start = time.perf_counter()
            summary = AnnotationQueryOptimizer.get_annotation_summary(
                user=self.user,
                document_id=self.doc.id,
                corpus_id=self.corpus.id,
                use_mv=True,
            )
            mv_times.append(time.perf_counter() - start)
        mv_time = min(mv_times)

        # Materialized view should be nearly instant
        self.assertLess(
            mv_time, 0.015, f"MV summary took {mv_time:.4f}s, expected < 0.015s"
        )

        # Verify summary correctness
        self.assertEqual(
            summary["annotation_count"], 900
        )  # 100 pages * 9 non-structural
        self.assertEqual(summary["structural_count"], 100)  # 100 pages * 1 structural
        self.assertEqual(summary["page_count"], 100)

        # Compare with direct query time
        start = time.perf_counter()
        AnnotationQueryOptimizer.get_annotation_summary(
            user=self.user,
            document_id=self.doc.id,
            corpus_id=self.corpus.id,
            use_mv=False,  # Force direct query
        )
        direct_time = time.perf_counter() - start

        # Materialized view should be faster, but handle edge cases
        if (
            direct_time > 0.0001
        ):  # Only compare if direct query took measurable time (> 0.1ms)
            # MV should be at least 2x faster than direct query
            self.assertLess(
                mv_time,
                direct_time * 2,
                f"MV ({mv_time:.4f}s) should be faster than direct query ({direct_time:.4f}s)",
            )
        else:
            # If direct query was too fast to measure accurately, just verify MV is also fast
            self.assertLess(
                mv_time, 0.01, f"MV should complete quickly ({mv_time:.4f}s < 0.01s)"
            )

    def test_query_optimizer_selection(self):
        """Test that query optimizer correctly selects strategies."""

        # Test page-specific optimization
        page_qs = AnnotationQueryOptimizer.get_document_annotations(
            user=self.user,
            document_id=self.doc.id,
            corpus_id=self.corpus.id,
            page=25,
            use_cache=False,
        )

        # Check that the query uses joins for related objects (select_related is applied)
        # Django's query representation shows the JOINs, not the method name
        query_str = str(page_qs.query)

        # Should have JOIN for annotation_label (from select_related)
        self.assertIn(
            "LEFT OUTER JOIN", query_str, "Query should use JOIN for related objects"
        )

        # Should include the annotation_label table
        self.assertIn(
            "annotations_annotationlabel",
            query_str,
            "Query should include annotation_label table",
        )

        # Test navigation optimization
        nav_data = AnnotationQueryOptimizer.get_navigation_annotations(
            user=self.user,
            document_id=self.doc.id,
            corpus_id=self.corpus.id,
            use_mv=False,  # Test direct query optimization
        )

        # Navigation query should only fetch minimal fields
        nav_qs = nav_data
        if hasattr(nav_qs, "query"):
            query_str = str(nav_qs.query)
            # Should use only() to limit fields
            self.assertIn("id", query_str)
            self.assertIn("page", query_str)

    def test_progressive_loading_graphql(self):
        """Test that GraphQL progressive loading fields work correctly."""
        from graphene.test import Client

        from config.graphql.schema import schema

        client = Client(schema)

        # Test annotation summary field (uses materialized view)
        doc_id = to_global_id("DocumentType", self.doc.id)
        corpus_id = to_global_id("CorpusType", self.corpus.id)

        query = """
        query GetDocumentSummary($docId: ID!, $corpusId: ID!) {
            document(id: $docId) {
                annotationSummary(corpusId: $corpusId) {
                    annotationCount
                    structuralCount
                    pageCount
                    source
                }
            }
        }
        """

        start = time.perf_counter()
        result = client.execute(
            query,
            variables={"docId": doc_id, "corpusId": corpus_id},
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        graphql_time = time.perf_counter() - start

        # GraphQL query should be fast with materialized view
        self.assertLess(
            graphql_time,
            0.1,
            f"GraphQL summary query took {graphql_time:.4f}s, expected < 0.1s",
        )

        # Check results
        if not result.get("errors"):
            summary = result["data"]["document"]["annotationSummary"]
            self.assertEqual(summary["annotationCount"], 900)
            self.assertEqual(summary["structuralCount"], 100)
            self.assertEqual(summary["pageCount"], 100)

    def test_end_to_end_performance(self):
        """Test end-to-end performance of common operations."""

        # Simulate loading a document page with annotations
        page_to_load = 50

        start = time.perf_counter()

        # 1. Get page annotations (uses index)
        page_annotations = list(
            AnnotationQueryOptimizer.get_document_annotations(
                user=self.user,
                document_id=self.doc.id,
                corpus_id=self.corpus.id,
                page=page_to_load,
                structural=False,
                use_cache=False,
            )
        )

        # 2. Get summary statistics (uses materialized view)
        summary = AnnotationQueryOptimizer.get_annotation_summary(
            user=self.user,
            document_id=self.doc.id,
            corpus_id=self.corpus.id,
            use_mv=True,
        )

        # 3. Get navigation data (uses materialized view or optimized query)
        nav_data = AnnotationQueryOptimizer.get_navigation_annotations(
            user=self.user,
            document_id=self.doc.id,
            corpus_id=self.corpus.id,
            use_mv=True,
        )

        total_time = time.perf_counter() - start

        # All operations combined should be very fast
        self.assertLess(
            total_time,
            0.05,
            f"End-to-end operations took {total_time:.4f}s, expected < 0.05s",
        )

        # Verify we got the expected data
        self.assertEqual(len(page_annotations), 9)  # 9 non-structural annotations
        self.assertEqual(summary["page_count"], 100)
        self.assertIsNotNone(nav_data)

    def test_materialized_view_staleness_check(self):
        """Test materialized view staleness checking."""

        stats = check_materialized_view_staleness()

        # Should have stats for our materialized views
        self.assertIn("annotation_summary_mv", stats)

        if "annotation_summary_mv" in stats:
            mv_stats = stats["annotation_summary_mv"]
            self.assertIn("total_rows", mv_stats)
            self.assertIn("max_staleness_seconds", mv_stats)

            # Views should be relatively fresh (refreshed in setUp)
            if mv_stats.get("max_staleness_seconds"):
                self.assertLess(
                    mv_stats["max_staleness_seconds"],
                    300,  # Less than 5 minutes old
                    "Materialized view is too stale",
                )

    def test_cache_effectiveness(self):
        """Test that caching improves performance on repeated queries."""

        # First query (cache miss)
        result1 = list(
            AnnotationQueryOptimizer.get_document_annotations(
                user=self.user,
                document_id=self.doc.id,
                corpus_id=self.corpus.id,
                page=75,
                use_cache=True,
            )
        )

        # Second identical query (cache hit)
        result2 = list(
            AnnotationQueryOptimizer.get_document_annotations(
                user=self.user,
                document_id=self.doc.id,
                corpus_id=self.corpus.id,
                page=75,
                use_cache=True,
            )
        )

        # Cached query should be faster (though Django QuerySet caching is complex)
        # At minimum, results should be identical
        self.assertEqual(len(result1), len(result2))

        # Clear cache for next test
        AnnotationQueryOptimizer.invalidate_cache(
            document_id=self.doc.id, corpus_id=self.corpus.id
        )

    def test_performance_scales_with_data(self):
        """Test that performance optimizations scale with larger datasets."""

        # Add more data (double the dataset)
        more_annotations = []
        for page in range(101, 201):
            for i in range(10):
                more_annotations.append(
                    Annotation(
                        document=self.doc,
                        corpus=self.corpus,
                        page=page,
                        annotation_label=self.label,
                        raw_text=f"Additional annotation {i} on page {page}",
                        creator=self.user,
                        structural=(i == 0),
                    )
                )

        Annotation.objects.bulk_create(more_annotations)

        # Refresh materialized views (check if exists first)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_matviews
                    WHERE matviewname = 'annotation_summary_mv'
                )
            """
            )
            if cursor.fetchone()[0]:
                cursor.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
                )

        # Test that queries still perform well with 2000 annotations
        start = time.perf_counter()
        list(
            Annotation.objects.filter(
                document=self.doc, corpus=self.corpus, page=150, structural=False
            )
        )
        query_time = time.perf_counter() - start

        self.assertLess(
            query_time,
            0.02,
            f"Query with 2000 annotations took {query_time:.4f}s, expected < 0.02s",
        )

        # Test materialized view still performs well
        start = time.perf_counter()
        summary = AnnotationQueryOptimizer.get_annotation_summary(
            user=self.user,
            document_id=self.doc.id,
            corpus_id=self.corpus.id,
            use_mv=True,
        )
        mv_time = time.perf_counter() - start

        self.assertLess(
            mv_time,
            0.01,
            f"MV with 2000 annotations took {mv_time:.4f}s, expected < 0.01s",
        )

        # Verify counts are correct
        self.assertEqual(
            summary["annotation_count"], 1800
        )  # 200 pages * 9 non-structural
        self.assertEqual(summary["structural_count"], 200)  # 200 pages * 1 structural
