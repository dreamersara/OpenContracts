"""
Performance Test Suite for Backend Optimizations

This test suite validates that the performance optimizations
achieve the expected improvements in query time and resource usage.
"""

import time

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import override_settings
from graphene_django.utils.testing import GraphQLTestCase
from graphql_relay import to_global_id

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document

User = get_user_model()


class PerformanceOptimizationTestCase(GraphQLTestCase):
    """
    Test suite for validating performance optimizations.
    """

    GRAPHQL_URL = "/graphql/"  # Fix: Add trailing slash

    @classmethod
    def setUpTestData(cls):
        """Create test data for performance testing."""
        # Create test user
        cls.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

        # Create test corpus
        cls.corpus = Corpus.objects.create(
            title="Test Corpus",
            description="Test corpus for performance testing",
            creator=cls.user,
        )

        # Create test document
        cls.document = Document.objects.create(
            title="Test Document",
            description="Test document for performance testing",
            creator=cls.user,
            page_count=100,
        )

        # Add document to corpus
        cls.corpus.documents.add(cls.document)

        # Create test labels
        cls.labels = []
        for i in range(10):
            label = AnnotationLabel.objects.create(
                text=f"Label {i}", color=f"#{i:06x}", creator=cls.user
            )
            cls.labels.append(label)

        # Create many test annotations to simulate real-world data
        annotations = []
        for page in range(1, 51):  # 50 pages with annotations
            for i in range(20):  # 20 annotations per page = 1000 total
                annotations.append(
                    Annotation(
                        document=cls.document,
                        corpus=cls.corpus,
                        page=page,
                        annotation_label=cls.labels[i % 10],
                        raw_text=f"Annotation text on page {page}, item {i}",
                        json={"start": i * 10, "end": (i * 10) + 50},
                        bounding_box={
                            "x1": 100 + (i * 20),
                            "y1": 100 + (i * 30),
                            "x2": 150 + (i * 20),
                            "y2": 130 + (i * 30),
                        },
                        structural=False,
                        creator=cls.user,
                    )
                )

        # Bulk create annotations for efficiency
        Annotation.objects.bulk_create(annotations)

        # Create some structural annotations
        structural_annotations = []
        for page in range(1, 101):  # All pages
            structural_annotations.append(
                Annotation(
                    document=cls.document,
                    corpus=cls.corpus,
                    page=page,
                    raw_text=f"Page {page} Header",
                    structural=True,
                    creator=cls.user,
                )
            )
        Annotation.objects.bulk_create(structural_annotations)

        # Refresh materialized views to ensure they contain test data
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("REFRESH MATERIALIZED VIEW document_annotation_summary")
            cursor.execute("REFRESH MATERIALIZED VIEW page_annotation_index")
            cursor.execute("REFRESH MATERIALIZED VIEW label_usage_stats")

    def setUp(self):
        """Set up for each test."""
        self.client.force_login(self.user)

    def test_annotation_manifest_performance(self):
        """Test that annotation manifest loads quickly."""
        query = """
            query GetAnnotationManifest($documentId: ID!, $corpusId: ID!) {
                document(id: $documentId) {
                    annotationManifest(corpusId: $corpusId) {
                        totalCount
                        structuralCount
                        corpusCount
                        pagesWithAnnotations
                        navigationIndex {
                            annotationId
                            page
                            labelText
                        }
                    }
                }
            }
        """

        # Convert to global IDs
        document_gid = to_global_id("DocumentType", self.document.id)
        corpus_gid = to_global_id("CorpusType", self.corpus.id)

        # Reset queries
        connection.queries_log.clear()

        start_time = time.time()
        response = self.query(
            query, variables={"documentId": document_gid, "corpusId": corpus_gid}
        )
        elapsed_time = time.time() - start_time

        # Verify response
        self.assertResponseNoErrors(response)
        content = response.json()
        self.assertIn("data", content)
        self.assertIn("document", content["data"])

        if content["data"]["document"]:
            manifest = content["data"]["document"]["annotationManifest"]
            self.assertIsNotNone(manifest)
            self.assertIn("totalCount", manifest)
            self.assertIn("structuralCount", manifest)
            self.assertIn("corpusCount", manifest)

        # Performance assertions
        query_count = len(connection.queries)
        print(f"Manifest query count: {query_count}")
        print(f"Manifest load time: {elapsed_time:.3f}s")

        # Should use materialized view - very few queries
        self.assertLess(query_count, 10, "Too many queries for manifest")
        # Should load quickly
        self.assertLess(elapsed_time, 0.5, "Manifest took too long to load")

    def test_page_annotations_performance(self):
        """Test that page-specific annotations load efficiently."""
        query = """
            query GetPageAnnotations($documentId: ID!, $page: Int!, $corpusId: ID!) {
                document(id: $documentId) {
                    pageAnnotations(page: $page, corpusId: $corpusId) {
                        edges {
                            node {
                                id
                                page
                                rawText
                                annotationLabel {
                                    text
                                }
                            }
                        }
                    }
                }
            }
        """

        # Convert to global IDs
        document_gid = to_global_id("DocumentType", self.document.id)
        corpus_gid = to_global_id("CorpusType", self.corpus.id)

        # Reset queries
        connection.queries_log.clear()

        start_time = time.time()
        response = self.query(
            query,
            variables={"documentId": document_gid, "page": 10, "corpusId": corpus_gid},
        )
        elapsed_time = time.time() - start_time

        # Verify response
        self.assertResponseNoErrors(response)
        content = response.json()
        self.assertIn("data", content)

        # Performance assertions
        query_count = len(connection.queries)
        print(f"Page annotations query count: {query_count}")
        print(f"Page annotations load time: {elapsed_time:.3f}s")

        # Should use optimized queries - minimal count
        self.assertLess(query_count, 5, "Too many queries for single page")
        # Should load quickly
        self.assertLess(elapsed_time, 0.1, "Page annotations took too long")

    def test_batch_page_annotations_performance(self):
        """Test that batch page loading is efficient."""
        query = """
            query GetBatchPages($documentId: ID!, $pages: [Int!]!, $corpusId: ID!) {
                document(id: $documentId) {
                    batchPageAnnotations(pages: $pages, corpusId: $corpusId) {
                        page
                        count
                        annotations {
                            id
                            rawText
                        }
                    }
                }
            }
        """

        # Convert to global IDs
        document_gid = to_global_id("DocumentType", self.document.id)
        corpus_gid = to_global_id("CorpusType", self.corpus.id)

        # Reset queries
        connection.queries_log.clear()

        start_time = time.time()
        response = self.query(
            query,
            variables={
                "documentId": document_gid,
                "pages": [1, 2, 3, 4, 5],
                "corpusId": corpus_gid,
            },
        )
        elapsed_time = time.time() - start_time

        # Verify response
        self.assertResponseNoErrors(response)
        content = response.json()
        self.assertIn("data", content)

        if (
            content["data"]["document"]
            and content["data"]["document"]["batchPageAnnotations"]
        ):
            batch_result = content["data"]["document"]["batchPageAnnotations"]
            self.assertIsInstance(batch_result, list)

        # Performance assertions
        query_count = len(connection.queries)
        print(f"Batch pages query count: {query_count}")
        print(f"Batch pages load time: {elapsed_time:.3f}s")

        # Should batch efficiently - not 5x single page queries
        self.assertLess(query_count, 10, "Too many queries for batch load")
        # Should load quickly even for multiple pages
        self.assertLess(elapsed_time, 0.3, "Batch load took too long")

    @override_settings(DEBUG=True)
    def test_all_annotations_optimization(self):
        """Test that the existing all_annotations field is optimized."""
        query = """
            query GetAllAnnotations($documentId: ID!, $corpusId: ID!) {
                document(id: $documentId) {
                    allAnnotations(corpusId: $corpusId) {
                        id
                        page
                        rawText
                        annotationLabel {
                            text
                            color
                        }
                        creator {
                            email
                        }
                    }
                }
            }
        """

        # Convert to global IDs
        document_gid = to_global_id("DocumentType", self.document.id)
        corpus_gid = to_global_id("CorpusType", self.corpus.id)

        # Reset queries
        connection.queries_log.clear()

        start_time = time.time()
        response = self.query(
            query, variables={"documentId": document_gid, "corpusId": corpus_gid}
        )
        elapsed_time = time.time() - start_time

        # Verify response
        self.assertResponseNoErrors(response)
        content = response.json()
        self.assertIn("data", content)

        # Performance assertions
        query_count = len(connection.queries)
        print(f"All annotations (optimized) query count: {query_count}")
        print(f"All annotations (optimized) load time: {elapsed_time:.3f}s")

        # Should use select_related and prefetch_related - minimal queries
        # Even with 1000+ annotations, should be under 25 queries
        self.assertLess(query_count, 25, "N+1 query problem detected")

    def test_cache_effectiveness(self):
        """Test that caching returns consistent correct data."""
        query = """
            query GetAnnotationManifest($documentId: ID!, $corpusId: ID!) {
                document(id: $documentId) {
                    annotationManifest(corpusId: $corpusId) {
                        totalCount
                        structuralCount
                        corpusCount
                        userAnnotationCount
                        analysisAnnotationCount
                        totalPages
                        cached
                    }
                }
            }
        """

        # Convert to global IDs
        document_gid = to_global_id("DocumentType", self.document.id)
        corpus_gid = to_global_id("CorpusType", self.corpus.id)

        # First request
        connection.queries_log.clear()
        response1 = self.query(
            query, variables={"documentId": document_gid, "corpusId": corpus_gid}
        )
        queries_first = len(connection.queries)

        # Second request
        connection.queries_log.clear()
        response2 = self.query(
            query, variables={"documentId": document_gid, "corpusId": corpus_gid}
        )
        queries_second = len(connection.queries)

        # Verify both responses are correct
        self.assertResponseNoErrors(response1)
        self.assertResponseNoErrors(response2)

        content1 = response1.json()
        content2 = response2.json()
        self.assertIn("data", content1)
        self.assertIn("data", content2)

        # Get manifest data
        manifest1 = content1["data"]["document"]["annotationManifest"]
        manifest2 = content2["data"]["document"]["annotationManifest"]

        print(f"First request queries: {queries_first}")
        print(f"Second request queries: {queries_second}")
        print(f"First request cached: {manifest1.get('cached', False)}")
        print(f"Second request cached: {manifest2.get('cached', False)}")

        # Both requests should return the same correct data
        self.assertIsNotNone(manifest1, "First request returned None")
        self.assertIsNotNone(manifest2, "Second request returned None")

        # Check data correctness - we have 1100 annotations (1000 regular + 100 structural)
        self.assertEqual(manifest1["totalCount"], 1100, "Incorrect total count")
        self.assertEqual(
            manifest1["structuralCount"], 100, "Incorrect structural count"
        )
        self.assertEqual(manifest1["corpusCount"], 1000, "Incorrect corpus count")

        # Both requests should return identical data
        self.assertEqual(
            manifest1["totalCount"],
            manifest2["totalCount"],
            "Total count mismatch between requests",
        )
        self.assertEqual(
            manifest1["structuralCount"],
            manifest2["structuralCount"],
            "Structural count mismatch between requests",
        )
        self.assertEqual(
            manifest1["corpusCount"],
            manifest2["corpusCount"],
            "Corpus count mismatch between requests",
        )
        self.assertEqual(
            manifest1["userAnnotationCount"],
            manifest2["userAnnotationCount"],
            "User annotation count mismatch between requests",
        )
        self.assertEqual(
            manifest1["analysisAnnotationCount"],
            manifest2["analysisAnnotationCount"],
            "Analysis annotation count mismatch between requests",
        )
        self.assertEqual(
            manifest1["totalPages"],
            manifest2["totalPages"],
            "Total pages mismatch between requests",
        )

        # If first request wasn't cached, second should be cached or use fewer queries
        if not manifest1.get("cached", False):
            self.assertTrue(
                manifest2.get("cached", False) or queries_second <= queries_first,
                "Cache not working - second request should be cached or use fewer queries",
            )
