"""
Tests for database optimization features including indexes.
"""

import time

from django.contrib.auth import get_user_model
from django.db import connection

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase

User = get_user_model()


class DatabaseIndexTestCase(BaseFixtureTestCase):
    """
    Test that database indexes are properly created and used.
    """

    def test_performance_indexes_exist(self):
        """Test that all performance indexes are created after migration"""

        with connection.cursor() as cursor:
            # Check if indexes exist by querying PostgreSQL system catalogs
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'annotations_annotation'
                AND indexname IN (
                    'idx_ann_doc_corpus_page_nonstruct',
                    'idx_ann_doc_corpus_page_user',
                    'idx_ann_doc_corpus_analysis_page',
                    'idx_ann_doc_page_struct'
                )
                ORDER BY indexname;
            """
            )

            annotation_indexes = [row[0] for row in cursor.fetchall()]

            # Check if all expected annotation indexes exist
            expected_annotation_indexes = [
                "idx_ann_doc_corpus_analysis_page",
                "idx_ann_doc_corpus_page_nonstruct",
                "idx_ann_doc_corpus_page_user",
                "idx_ann_doc_page_struct",
            ]

            for idx in expected_annotation_indexes:
                self.assertIn(
                    idx, annotation_indexes, f"Index {idx} not found in database"
                )

            # Check relationship index
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'annotations_relationship'
                AND indexname = 'idx_relationship_corpus_doc_struct';
            """
            )

            relationship_indexes = [row[0] for row in cursor.fetchall()]
            self.assertIn(
                "idx_relationship_corpus_doc_struct",
                relationship_indexes,
                "Relationship index not found",
            )

            # Note: Feedback index removed from migration since feedback app may not be installed
            # If you need to test feedback indexes, they should be in the feedback app's migrations

    def test_index_usage_for_common_queries(self):
        """Test that indexes are used for common query patterns"""

        # Create test data
        corpus = Corpus.objects.create(title="Test Corpus for Index", creator=self.user)

        label = AnnotationLabel.objects.create(text="Test Label", creator=self.user)

        # Create many annotations to make index usage more likely
        annotations = []
        for page in range(1, 11):
            for i in range(10):
                annotations.append(
                    Annotation(
                        document=self.doc,
                        corpus=corpus,
                        page=page,
                        annotation_label=label,
                        raw_text=f"Test annotation {i} on page {page}",
                        creator=self.user,
                        structural=False,
                    )
                )

        Annotation.objects.bulk_create(annotations)

        # Test query with EXPLAIN to verify index usage
        with connection.cursor() as cursor:
            # Test non-structural page query
            cursor.execute(
                """
                EXPLAIN (FORMAT JSON)
                SELECT * FROM annotations_annotation
                WHERE document_id = %s
                AND corpus_id = %s
                AND page = %s
                AND structural = false;
            """,
                [self.doc.id, corpus.id, 5],
            )

            plan = cursor.fetchone()[0][0]

            # Check if an index scan is being used (not a sequential scan)
            # The exact index name might vary based on optimizer choices
            plan_str = str(plan)
            self.assertTrue(
                "Index Scan" in plan_str or "Bitmap Index Scan" in plan_str,
                f"Query not using index scan. Plan: {plan_str}",
            )

    def test_query_performance_with_indexes(self):
        """Test that indexed queries perform within acceptable time bounds"""

        # Create a larger dataset for performance testing
        corpus = Corpus.objects.create(
            title="Performance Test Corpus", creator=self.user
        )

        label = AnnotationLabel.objects.create(
            text="Performance Label", creator=self.user
        )

        # Create 1000 annotations
        annotations = []
        for page in range(1, 101):
            for i in range(10):
                annotations.append(
                    Annotation(
                        document=self.doc,
                        corpus=corpus,
                        page=page,
                        annotation_label=label,
                        raw_text=f"Performance test annotation {i} on page {page}",
                        creator=self.user,
                        structural=(i % 5 == 0),  # 20% structural
                    )
                )

        Annotation.objects.bulk_create(annotations)

        # Test query performance
        start_time = time.perf_counter()

        # This query should use idx_ann_doc_corpus_page_nonstruct
        result = list(
            Annotation.objects.filter(
                document=self.doc,
                corpus=corpus,
                page__in=[10, 20, 30],
                structural=False,
            )
        )

        query_time = time.perf_counter() - start_time

        # Should be very fast with index (under 50ms even with 1000 records)
        self.assertLess(
            query_time,
            0.05,
            f"Query took {query_time:.4f} seconds, expected < 0.05s with index",
        )

        # Verify we got the expected results
        self.assertEqual(len(result), 24)  # 3 pages * 8 non-structural per page


class QueryOptimizerTestCase(BaseFixtureTestCase):
    """
    Test the AnnotationQueryOptimizer functionality.
    """

    def setUp(self):
        super().setUp()
        # Create test data
        self.corpus = Corpus.objects.create(
            title="Optimizer Test Corpus", creator=self.user
        )

        self.label = AnnotationLabel.objects.create(
            text="Optimizer Test Label", creator=self.user
        )

    def test_get_document_annotations_with_page_filter(self):
        """Test optimized query with page filter"""
        # Create test annotations
        for page in [1, 2, 3]:
            for i in range(3):
                Annotation.objects.create(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"Test annotation {i} on page {page}",
                    creator=self.user,
                    structural=False,
                )

        # Test page-specific query
        result = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.doc.id,
            user=self.user,
            corpus_id=self.corpus.id,
            page=2,
            use_cache=False,
        )

        annotations = list(result)
        self.assertEqual(len(annotations), 3)
        self.assertTrue(all(a.page == 2 for a in annotations))

    def test_get_annotation_summary_fallback(self):
        """Test annotation summary with fallback to direct query"""
        # Create test annotations
        for page in [1, 3, 5]:
            for i in range(4):
                Annotation.objects.create(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"Summary test {i} on page {page}",
                    creator=self.user,
                    structural=(i == 0),  # First one is structural
                )

        # Get summary (will use direct query since MV might not be refreshed)
        summary = AnnotationQueryOptimizer.get_annotation_summary(
            document_id=self.doc.id,
            corpus_id=self.corpus.id,
            user=self.user,
            use_mv=False,  # Force direct query for testing
        )

        self.assertEqual(summary["annotation_count"], 9)  # 3 pages * 3 non-structural
        self.assertEqual(summary["structural_count"], 3)  # 3 pages * 1 structural
        self.assertEqual(
            summary["user_annotation_count"], 9
        )  # All non-structural are user annots
        self.assertEqual(summary["page_count"], 3)
        self.assertEqual(summary["first_page"], 1)
        self.assertEqual(summary["last_page"], 5)
        self.assertEqual(summary["source"], "direct_query")

    def test_get_navigation_annotations(self):
        """Test navigation annotation retrieval"""
        # Create test annotations with bounding boxes
        test_annotations = []
        for page in [1, 2]:
            for i in range(2):
                ann = Annotation.objects.create(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"Nav test {i} on page {page}",
                    creator=self.user,
                    structural=False,
                    bounding_box={
                        "x": i * 100,
                        "y": page * 100,
                        "width": 50,
                        "height": 20,
                    },
                )
                test_annotations.append(ann)

        # Also create a structural annotation that should be excluded
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=self.label,
            raw_text="Structural - should not appear",
            creator=self.user,
            structural=True,
        )

        # Get navigation annotations
        nav_annotations = AnnotationQueryOptimizer.get_navigation_annotations(
            document_id=self.doc.id,
            corpus_id=self.corpus.id,
            user=self.user,
            use_mv=False,  # Force direct query for testing
        )

        # Convert to list for testing
        nav_list = list(nav_annotations)
        self.assertEqual(len(nav_list), 4)  # Only non-structural

        # Verify ordering and that structural annotation is excluded
        for ann in nav_list:
            self.assertFalse(ann.structural)
            self.assertIsNotNone(ann.bounding_box)

    def test_query_optimizer_performance(self):
        """Test that optimizer provides performance benefits"""
        # Create larger dataset
        annotations = []
        for page in range(1, 51):  # 50 pages
            for i in range(20):  # 20 annotations per page
                annotations.append(
                    Annotation(
                        document=self.doc,
                        corpus=self.corpus,
                        page=page,
                        annotation_label=self.label,
                        raw_text=f"Perf test {i} on page {page}",
                        creator=self.user,
                        structural=(i < 2),  # 10% structural
                    )
                )

        Annotation.objects.bulk_create(annotations)

        # Time optimized query
        start = time.perf_counter()
        result = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.doc.id,
            user=self.user,
            corpus_id=self.corpus.id,
            page=25,
            structural=False,
            use_cache=False,
        )
        list(result)  # Force evaluation
        optimized_time = time.perf_counter() - start

        # Should be fast even with 1000 annotations
        self.assertLess(
            optimized_time,
            0.05,
            f"Optimized query took {optimized_time:.4f}s, expected < 0.05s",
        )
